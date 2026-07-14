"""039/009 — pricing simulator: manifests, exact transforms, replay modes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from cloud.billing import simulator
from cloud.billing.ledger import create_grant, ensure_billing_account
from cloud.billing.models import (
    AgentHostingPeriod,
    BillableEvent,
    BillingJob,
    CreditLedgerTransaction,
    RatedCharge,
    StripePayment,
)
from cloud.billing.seed import commercial_v1_config, seed_commercial_v1
from cloud.billing.simulator import (
    SimulationError,
    build_manifest,
    create_simulation,
    canonical_filters,
    parse_decimal_rational,
    parse_transforms,
    result_csv,
    run_simulation,
    _handle_pricing_sim,
)
from cloud.billing.versions import create_draft_version

NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)
WINDOW = {
    "period_start": (NOW - timedelta(days=7)).isoformat(),
    "period_end": NOW.isoformat(),
}

asyncio_test = pytest.mark.asyncio


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _event(account_id, op, *, attempt=1, vendor=25_000, model="gpt-4o",
           context="agent", at=None, usage=True, status="recorded"):
    return BillableEvent(
        source_idempotency_key=f"{op}:{attempt}",
        call_id=op,
        account_id=account_id,
        service="llm",
        sku="llm_call",
        context=context,
        provider="openai",
        model=model,
        attempt_number=attempt,
        quantity_json={"input_tokens": 100, "output_tokens": 50} if usage else None,
        vendor_cost_micro_usd=vendor,
        cost_source="provider_usage",
        status=status,
        event_at=at or (NOW - timedelta(days=1)),
    )


async def _versions(db_session, *, candidate_config=None):
    """Published baseline (launch v1) + a draft candidate."""
    baseline = await seed_commercial_v1(db_session)
    config = candidate_config or commercial_v1_config()
    candidate = await create_draft_version(db_session, name="candidate", config=config)
    await db_session.flush()
    return baseline, candidate


def _double_margin_config():
    config = commercial_v1_config()
    config["llm_constants"]["agent"]["mid"] = 20_000  # baseline is 10_000
    return config


async def _make_sim(db_session, account, *, events, candidate_config=None, **kwargs):
    await ensure_billing_account(db_session, account.id)
    db_session.add_all(events)
    await db_session.flush()
    baseline, candidate = await _versions(db_session, candidate_config=candidate_config)
    sim = await create_simulation(
        db_session,
        filters=dict(WINDOW),
        baseline_version_id=baseline.id,
        candidate_version_id=candidate.id,
        **kwargs,
    )
    await db_session.flush()
    return sim


# ── Exact rationals and transform validation ─────────────────────────────────

def test_parse_decimal_rational_exact():
    assert parse_decimal_rational("0.50") == (1, 2)
    assert parse_decimal_rational("1.25") == (5, 4)
    assert parse_decimal_rational("2") == (2, 1)
    assert parse_decimal_rational(3) == (3, 1)
    assert parse_decimal_rational("0") == (0, 1)


def test_parse_decimal_rational_rejects_floats_and_junk():
    for bad in (0.5, True, -1, "-0.5", "1.2.3", "abc", "1.", None, [1]):
        with pytest.raises(SimulationError):
            parse_decimal_rational(bad)


def test_parse_transforms_validation():
    with pytest.raises(SimulationError, match="unknown transform"):
        parse_transforms({"discount": "0.5"})
    with pytest.raises(SimulationError, match="multiplier"):
        parse_transforms({"cost_multipliers": [{"provider": "openai"}]})
    with pytest.raises(SimulationError, match="llm_constants"):
        parse_transforms({"llm_constants": {"agent": {"mid": 1.5}}})
    t = parse_transforms({
        "cost_multiplier": "0.50",
        "cost_multipliers": [{"provider": "openai", "multiplier": "0.25"}],
    })
    assert t.cost_factor("openai", "gpt-4o", "agent") == (1, 4)  # specific wins
    assert t.cost_factor("anthropic", "claude-opus-4-6", "agent") == (1, 2)


def test_canonical_filters_stable_and_strict():
    a = canonical_filters({"period_start": WINDOW["period_start"],
                           "period_end": WINDOW["period_end"],
                           "providers": ["openai", "anthropic"]})
    b = canonical_filters({"providers": ["anthropic", "openai"],
                           "period_end": WINDOW["period_end"],
                           "period_start": WINDOW["period_start"]})
    assert a == b
    with pytest.raises(SimulationError, match="unknown filter"):
        canonical_filters({"tenant": "x"})
    with pytest.raises(SimulationError, match="precede"):
        canonical_filters({"period_start": WINDOW["period_end"],
                           "period_end": WINDOW["period_start"]})


# ── Manifest guarantees ──────────────────────────────────────────────────────

@asyncio_test
async def test_event_cap_is_an_error_not_sampling(db_session, account, monkeypatch):
    await ensure_billing_account(db_session, account.id)
    db_session.add_all([_event(account.id, f"op-{i}") for i in range(3)])
    await db_session.flush()
    monkeypatch.setattr(simulator, "MAX_EVENTS", 2)
    baseline, candidate = await _versions(db_session)
    with pytest.raises(SimulationError, match="narrow the filters"):
        await build_manifest(db_session, filters=dict(WINDOW),
                             baseline_version_id=baseline.id,
                             candidate_version_id=candidate.id)


@asyncio_test
async def test_volume_multiplier_rejected_with_wallet_replay(db_session, account):
    baseline, candidate = await _versions(db_session)
    with pytest.raises(SimulationError, match="full_demand"):
        await build_manifest(db_session, filters=dict(WINDOW),
                             baseline_version_id=baseline.id,
                             candidate_version_id=candidate.id,
                             transforms={"volume_multiplier": "2"},
                             replay_mode="wallet_constrained")


@asyncio_test
async def test_manifest_snapshots_configs_and_events(db_session, account):
    sim = await _make_sim(db_session, account,
                          events=[_event(account.id, "op-1")],
                          candidate_config=_double_margin_config())
    m = sim.manifest
    assert m["event_count"] == 1 and m["algorithm_version"] == 1
    assert m["baseline_config"]["llm_constants"]["agent"]["mid"] == 10_000
    assert m["candidate_config"]["llm_constants"]["agent"]["mid"] == 20_000
    assert m["provider_cost_version_id"] is None  # original_snapshot pins none
    # The durable job exists with the dedupe key.
    job = (await db_session.execute(
        select(BillingJob).where(BillingJob.job_type == "pricing_sim")
    )).scalar_one()
    assert job.dedupe_key == f"pricing_sim:{sim.id}"


# ── Hand-calculated aggregate fixture ────────────────────────────────────────

@asyncio_test
async def test_aggregate_matches_hand_calculation(db_session, account):
    # Two accepted single-attempt agent/mid calls, stored vendor costs
    # 25_000 and 3_000 micro-USD. Baseline margin 10_000; candidate 20_000.
    #   baseline: ceil(35_000/10_000)=4 + ceil(13_000/10_000)=2 → 6 credits
    #   candidate: ceil(45_000/10_000)=5 + ceil(23_000/10_000)=3 → 8 credits
    sim = await _make_sim(
        db_session, account,
        events=[_event(account.id, "op-1", vendor=25_000),
                _event(account.id, "op-2", vendor=3_000)],
        candidate_config=_double_margin_config(),
    )
    result = await run_simulation(db_session, sim)
    base, cand = result["baseline"], result["candidate"]
    assert (base["credits"], cand["credits"]) == (6, 8)
    assert base["vendor_micro_usd"] == cand["vendor_micro_usd"] == 28_000
    assert base["margin_micro_usd"] == 20_000 and cand["margin_micro_usd"] == 40_000
    assert base["face_value_micro_usd"] == 60_000
    assert cand["face_value_micro_usd"] == 80_000
    # face − vendor − margin = rounding, exactly.
    assert base["rounding_micro_usd"] == 60_000 - 28_000 - 20_000
    assert cand["rounding_micro_usd"] == 80_000 - 28_000 - 40_000
    assert base["gross_profit_face_micro_usd"] == 32_000
    assert result["delta"]["credits"] == 2
    assert result["labels"]["face_value"] == "credit face value (not cash revenue)"
    # full_demand has no cash story.
    assert base["cash_basis_micro_usd"] is None


@asyncio_test
async def test_failed_attempts_absorbed_and_rated_once(db_session, account):
    # Attempt 1 failed (7_000 absorbed), attempt 2 accepted (25_000 billable).
    # A rated charge with status_code 200 marks the call accepted.
    events = [
        _event(account.id, "op-1", attempt=1, vendor=7_000, usage=False),
        _event(account.id, "op-1", attempt=2, vendor=25_000),
    ]
    sim = await _make_sim(db_session, account, events=events)
    db_session.add(RatedCharge(logical_call_id="op-1", account_id=account.id,
                               credits=4, charge_status="observed",
                               rule_snapshot={"status_code": 200}))
    await db_session.flush()
    result = await run_simulation(db_session, sim)
    base = result["baseline"]
    assert result["logical_calls"] == 1
    assert base["credits"] == 4  # ceil((25_000+10_000)/10_000), one margin, one ceil
    assert base["vendor_micro_usd"] == 25_000
    assert base["luna_absorbed_micro_usd"] == 7_000


@asyncio_test
async def test_uncovered_model_is_unpriced_never_guessed(db_session, account):
    sim = await _make_sim(db_session, account,
                          events=[_event(account.id, "op-1", model="mystery-model")])
    result = await run_simulation(db_session, sim)
    assert result["baseline"]["unpriced_calls"] == 1
    assert result["baseline"]["credits"] == 0


# ── Exact transforms ─────────────────────────────────────────────────────────

@asyncio_test
async def test_half_cost_transform_exact_integers(db_session, account):
    # Odd vendor cost 25_001 × "0.50" stays rational until the single ceil:
    # candidate vendor = ceil(25_001/2) = 12_501,
    # credits = ceil((25_001 + 2·10_000) / (2·10_000)) = ceil(45_001/20_000) = 3.
    sim = await _make_sim(db_session, account,
                          events=[_event(account.id, "op-1", vendor=25_001)],
                          transforms={"cost_multiplier": "0.50"})
    result = await run_simulation(db_session, sim)
    base, cand = result["baseline"], result["candidate"]
    assert base["credits"] == 4 and base["vendor_micro_usd"] == 25_001
    assert cand["credits"] == 3 and cand["vendor_micro_usd"] == 12_501
    for side in (base, cand):
        for key, value in side.items():
            if key != "unrated_dimensions":
                assert not isinstance(value, float), f"{key} leaked a float"


@asyncio_test
async def test_volume_multiplier_scales_aggregates(db_session, account):
    # Baseline 6 credits; candidate ×1.5 → ceil(6·3/2) = 9 credits.
    sim = await _make_sim(
        db_session, account,
        events=[_event(account.id, "op-1", vendor=25_000),
                _event(account.id, "op-2", vendor=3_000)],
        transforms={"volume_multiplier": "1.5"},
    )
    result = await run_simulation(db_session, sim)
    assert result["baseline"]["credits"] == 6
    assert result["candidate"]["credits"] == 9
    assert result["candidate"]["face_value_micro_usd"] == 90_000


@asyncio_test
async def test_margin_override_transform(db_session, account):
    # llm_constants transform: candidate agent/mid margin 0 → vendor-only ceil.
    sim = await _make_sim(db_session, account,
                          events=[_event(account.id, "op-1", vendor=25_000)],
                          transforms={"llm_constants": {"agent": {"mid": 0}}})
    result = await run_simulation(db_session, sim)
    assert result["baseline"]["credits"] == 4
    assert result["candidate"]["credits"] == 3  # ceil(25_000/10_000)


# ── Reproducibility ──────────────────────────────────────────────────────────

@asyncio_test
async def test_rerun_by_manifest_identical_after_late_event(db_session, account):
    sim = await _make_sim(db_session, account,
                          events=[_event(account.id, "op-1")],
                          candidate_config=_double_margin_config())
    first = await run_simulation(db_session, sim)

    # A late event lands inside the window after the manifest was built.
    db_session.add(_event(account.id, "op-late"))
    await db_session.flush()

    rerun = await create_simulation(db_session, manifest=sim.manifest)
    second = await run_simulation(db_session, rerun)
    assert second["result_hash"] == first["result_hash"]
    assert second["event_count"] == 1

    # A fresh manifest does see the late event — the difference is the point.
    fresh = await create_simulation(
        db_session, filters=dict(WINDOW),
        baseline_version_id=sim.baseline_version_id,
        candidate_version_id=sim.candidate_version_id,
    )
    assert fresh.manifest["event_count"] == 2


@asyncio_test
async def test_rerating_never_mutates_production_records(db_session, account):
    events = [_event(account.id, "op-1", vendor=25_000)]
    sim = await _make_sim(db_session, account, events=events,
                          candidate_config=_double_margin_config())
    before_vendor = [e.vendor_cost_micro_usd for e in events]
    txn_count = (await db_session.execute(
        select(func.count(CreditLedgerTransaction.id))
    )).scalar_one()
    await run_simulation(db_session, sim)
    await db_session.flush()
    assert [e.vendor_cost_micro_usd for e in events] == before_vendor
    assert (await db_session.execute(
        select(func.count(CreditLedgerTransaction.id))
    )).scalar_one() == txn_count
    assert (await db_session.execute(
        select(func.count(RatedCharge.id))
    )).scalar_one() == 0


@asyncio_test
async def test_deleted_events_surface_as_missing_never_guessed(db_session, account):
    events = [_event(account.id, "op-1"), _event(account.id, "op-2")]
    sim = await _make_sim(db_session, account, events=events)
    await db_session.delete(events[1])
    await db_session.flush()
    result = await run_simulation(db_session, sim)
    assert result["missing_events"] == 1
    assert result["logical_calls"] == 1


# ── Wallet-constrained replay ────────────────────────────────────────────────

@asyncio_test
async def test_same_timestamp_events_replay_deterministically(db_session, account):
    # 5-credit wallet; three simultaneous 4-credit calls. Deterministic order
    # (event_at, operation_id): op-a charges (balance 1), op-b posts into
    # debt (balance −3), op-c is blocked at the ≤0 gate.
    at = NOW - timedelta(days=1)
    events = [_event(account.id, op, vendor=30_000, at=at)
              for op in ("op-a", "op-b", "op-c")]
    sim = await _make_sim(db_session, account, events=events,
                          replay_mode="wallet_constrained")
    await create_grant(db_session, account_id=account.id, source_type="gift",
                       source_key="sim:gift", credits=5, visible_category="gift",
                       effective_at=NOW - timedelta(days=3), expires_at=None,
                       now=NOW - timedelta(days=3))
    first = await run_simulation(db_session, sim)
    second = await run_simulation(db_session, sim)
    assert first["result_hash"] == second["result_hash"]
    side = first["baseline"]
    assert side["credits"] == 8 and side["blocked_calls"] == 1
    assert side["blocked_credits"] == 4
    assert side["accounts_in_debt"] == 1 and side["accounts_hit_zero"] == 1


@asyncio_test
async def test_bonus_grants_cut_cash_basis_not_face_value(db_session, account):
    # Burn priority spends the bonus lot before the paid lot, so a 4-credit
    # call has full face value but zero cash basis.
    events = [_event(account.id, "op-1", vendor=30_000)]
    sim = await _make_sim(db_session, account, events=events,
                          replay_mode="wallet_constrained")
    effective = NOW - timedelta(days=3)
    await create_grant(db_session, account_id=account.id, source_type="subscription_bonus",
                       source_key="sim:bonus", credits=10, visible_category="bonus",
                       effective_at=effective, expires_at=None, now=effective)
    await create_grant(db_session, account_id=account.id, source_type="subscription_paid",
                       source_key="sim:paid", credits=10, visible_category="paid",
                       effective_at=effective, expires_at=None,
                       cash_paid_micro_usd=100_000, now=effective)
    result = await run_simulation(db_session, sim)
    side = result["baseline"]
    assert side["credits"] == 4
    assert side["face_value_micro_usd"] == 40_000
    assert side["cash_basis_micro_usd"] == 0
    assert side["subsidy_credits"] == 4
    assert side["gross_profit_face_micro_usd"] == 40_000 - 30_000
    assert side["gross_profit_cash_micro_usd"] == 0 - 30_000
    assert result["labels"]["cash_basis"] == "consumed cash-backed lots only"


@asyncio_test
async def test_funding_modes_produce_labeled_differences(db_session, account):
    events = [_event(account.id, "op-1", vendor=30_000)]
    sim = await _make_sim(db_session, account, events=events,
                          replay_mode="wallet_constrained",
                          funding_mode="candidate_products")
    # A historical payment on a product key the candidate catalog dropped:
    # counted as unmapped, funds nothing, so the call blocks.
    db_session.add(StripePayment(
        account_id=account.id, payment_ref="invoice:legacy-1", kind="subscription",
        product_key="legacy_plan", pretax_amount_cents=1_900, granted_credits=1_900,
        created_at=NOW - timedelta(days=30),
    ))
    await db_session.flush()
    result = await run_simulation(db_session, sim)
    assert result["funding_mode"] == "candidate_products"
    assert result["wallet"]["unmapped_payments"] == 1
    assert result["baseline"]["blocked_calls"] == 1

    # The same demand under actual grants charges normally — the two funding
    # modes answer different questions and both carry their mode label.
    sim2 = await create_simulation(
        db_session, filters=dict(WINDOW),
        baseline_version_id=sim.baseline_version_id,
        candidate_version_id=sim.candidate_version_id,
        replay_mode="wallet_constrained", funding_mode="actual_grants",
    )
    await create_grant(db_session, account_id=account.id, source_type="gift",
                       source_key="sim:gift2", credits=100, visible_category="gift",
                       effective_at=NOW - timedelta(days=3), expires_at=None,
                       now=NOW - timedelta(days=3))
    result2 = await run_simulation(db_session, sim2)
    assert result2["funding_mode"] == "actual_grants"
    assert result2["baseline"]["blocked_calls"] == 0
    assert result2["baseline"]["credits"] == 4


@asyncio_test
async def test_candidate_products_map_topups_and_subscriptions(db_session, account):
    events = [_event(account.id, "op-1", vendor=30_000)]
    sim = await _make_sim(db_session, account, events=events,
                          replay_mode="wallet_constrained",
                          funding_mode="candidate_products")
    db_session.add(StripePayment(
        account_id=account.id, payment_ref="pi:topup-1", kind="topup",
        product_key="topup_10", pretax_amount_cents=1_000, granted_credits=1_000,
        created_at=NOW - timedelta(days=30),
    ))
    await db_session.flush()
    result = await run_simulation(db_session, sim)
    side = result["baseline"]
    assert result["wallet"]["unmapped_payments"] == 0
    assert side["credits"] == 4 and side["blocked_calls"] == 0
    assert side["cash_basis_micro_usd"] == 40_000  # topup lots are cash-backed


# ── Hosting replay ───────────────────────────────────────────────────────────

@asyncio_test
async def test_hosting_credits_replay_config_price(db_session, account, sample_agent):
    sim = await _make_sim(db_session, account, events=[_event(account.id, "op-1")])
    db_session.add(AgentHostingPeriod(
        agent_id=sample_agent.id, account_id=account.id,
        starts_at=NOW - timedelta(days=2), ends_at=NOW + timedelta(days=28),
        price_credits=999, state="active",
    ))
    await db_session.flush()
    result = await run_simulation(db_session, sim)
    assert result["baseline"]["hosting_credits"] == 999  # config price × 1 period


# ── Job lifecycle ────────────────────────────────────────────────────────────

@asyncio_test
async def test_cancelled_simulation_never_publishes(db_session, account):
    sim = await _make_sim(db_session, account, events=[_event(account.id, "op-1")])
    job = (await db_session.execute(
        select(BillingJob).where(BillingJob.job_type == "pricing_sim")
    )).scalar_one()
    sim.state = "cancelled"
    await db_session.flush()
    out = await _handle_pricing_sim(db_session, job)
    assert out == {"state": "cancelled"}
    assert sim.result is None and sim.state == "cancelled"


@asyncio_test
async def test_retried_job_is_idempotent_on_success(db_session, account):
    sim = await _make_sim(db_session, account, events=[_event(account.id, "op-1")])
    job = (await db_session.execute(
        select(BillingJob).where(BillingJob.job_type == "pricing_sim")
    )).scalar_one()
    first = await _handle_pricing_sim(db_session, job)
    assert first["state"] == "succeeded" and sim.state == "succeeded"
    published = sim.result
    again = await _handle_pricing_sim(db_session, job)  # lease-expiry retry
    assert again["result_hash"] == first["result_hash"]
    assert sim.result is published  # untouched, not recomputed


@asyncio_test
async def test_config_errors_fail_the_run_not_the_job(db_session, account):
    sim = await _make_sim(db_session, account, events=[_event(account.id, "op-1")])
    sim.manifest = dict(sim.manifest, transforms={"volume_multiplier": 0.5})  # float
    job = (await db_session.execute(
        select(BillingJob).where(BillingJob.job_type == "pricing_sim")
    )).scalar_one()
    out = await _handle_pricing_sim(db_session, job)
    assert out["state"] == "failed"
    assert sim.state == "failed" and "error" in sim.result


@asyncio_test
async def test_result_csv(db_session, account):
    sim = await _make_sim(db_session, account,
                          events=[_event(account.id, "op-1", vendor=25_000)],
                          candidate_config=_double_margin_config())
    sim.result = await run_simulation(db_session, sim)
    csv = result_csv(sim)
    lines = csv.strip().split("\n")
    assert lines[0].startswith("account_id,baseline_credits,candidate_credits")
    assert lines[1] == f"{account.id},4,5,1,0,0"
