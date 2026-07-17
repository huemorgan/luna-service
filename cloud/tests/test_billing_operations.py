"""039/009 — operations: counters, ledger invariants, alert lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cloud.billing import operations
from cloud.billing.ledger import (
    CONSUMED,
    WALLET,
    charge,
    create_grant,
    ensure_billing_account,
    reverse_transaction,
)
from cloud.billing.models import (
    AccountBalanceProjection,
    AgentHostingPeriod,
    BillableEvent,
    BillingHold,
    CreditGrant,
    CreditLedgerPosting,
    OpsAlert,
    ProcessedWebhook,
    RatedCharge,
    StripePayment,
    StripePriceBinding,
)
from cloud.billing.operations import (
    check_grant_remainders,
    check_projection_drift,
    check_trial_balance,
    evaluate_alerts,
    heartbeat,
    ops_snapshot,
    run_invariants,
)
from cloud.billing.worker import enqueue, fail_job

NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)

asyncio_test = pytest.mark.asyncio


async def _funded_account(db_session, account, credits=100):
    await ensure_billing_account(db_session, account.id)
    await create_grant(db_session, account_id=account.id, source_type="gift",
                       source_key=f"ops:{uuid.uuid4()}", credits=credits,
                       visible_category="gift", effective_at=NOW - timedelta(days=1),
                       expires_at=None, now=NOW - timedelta(days=1))


async def _dead_job(db_session, job_type):
    job = await enqueue(db_session, job_type=job_type, payload={}, max_attempts=1)
    job.attempts = 1
    await fail_job(db_session, job, error="boom", now=NOW)
    assert job.status == "dead"
    return job


# ── Heartbeats ───────────────────────────────────────────────────────────────

@asyncio_test
async def test_heartbeat_upsert(db_session):
    await heartbeat(db_session, "worker", {"n": 1})
    await heartbeat(db_session, "worker", {"n": 2})
    rows = await operations.heartbeats(db_session)
    assert len(rows) == 1
    assert rows[0]["name"] == "worker" and rows[0]["detail"] == {"n": 2}


# ── Invariants ───────────────────────────────────────────────────────────────

@asyncio_test
async def test_invariants_hold_after_normal_activity(db_session, account):
    await _funded_account(db_session, account)
    txn = await charge(db_session, account_id=account.id, credits=30,
                       idempotency_key="ops:c1", now=NOW)
    await reverse_transaction(db_session, transaction_id=txn.id, reason="test", actor="ops")
    await charge(db_session, account_id=account.id, credits=10,
                 idempotency_key="ops:c2", now=NOW)
    result = await run_invariants(db_session)
    assert result["trial_balance"]["ok"]
    assert result["projection_drift"]["ok"]
    assert result["grant_remainders"]["ok"]


@asyncio_test
async def test_trial_balance_flags_unbalanced_transaction(db_session, account):
    await _funded_account(db_session, account)
    posting = (await db_session.execute(select(CreditLedgerPosting).limit(1))).scalar_one()
    posting.credits += 7  # corrupt one leg directly, bypassing the engine
    await db_session.flush()
    result = await check_trial_balance(db_session)
    assert not result["ok"]
    assert result["total"] == 7
    assert result["unbalanced_transactions"][0]["sum"] == 7


@asyncio_test
async def test_projection_drift_detected(db_session, account):
    await _funded_account(db_session, account)
    projection = (await db_session.execute(select(AccountBalanceProjection))).scalar_one()
    projection.posted_balance_credits += 5
    await db_session.flush()
    result = await check_projection_drift(db_session)
    assert not result["ok"]
    assert result["drifted"][0]["projected_balance"] == result["drifted"][0]["ledger_balance"] + 5


@asyncio_test
async def test_grant_remainder_drift_detected_and_reversals_excluded(db_session, account):
    await _funded_account(db_session, account, credits=50)
    txn = await charge(db_session, account_id=account.id, credits=20,
                       idempotency_key="ops:c1", now=NOW)
    # A reversed charge's consumption rows must not count against the grant.
    await reverse_transaction(db_session, transaction_id=txn.id, reason="refund", actor="ops")
    assert (await check_grant_remainders(db_session))["ok"]

    grant = (await db_session.execute(select(CreditGrant))).scalar_one()
    grant.remaining_credits -= 3
    await db_session.flush()
    result = await check_grant_remainders(db_session)
    assert not result["ok"]
    assert result["drifted"][0]["remaining"] == result["drifted"][0]["expected"] - 3


# ── Snapshot counters ────────────────────────────────────────────────────────

@asyncio_test
async def test_ops_snapshot_counters(db_session, account):
    await _funded_account(db_session, account)

    db_session.add_all([
        BillingHold(operation_id="op-1", request_hash="h", account_id=account.id,
                    status="open", estimated_credits=5),
        BillingHold(operation_id="op-2", request_hash="h", account_id=account.id,
                    status="needs_reconciliation", estimated_credits=9),
        RatedCharge(logical_call_id="c-1", account_id=account.id, credits=2,
                    charge_status="needs_reconciliation",
                    rule_snapshot={"unrated_dimensions": ["openai:gpt-4o:cache_write"]},
                    created_at=NOW),
        # Face 10_000 < vendor 15_000 → negative margin.
        RatedCharge(logical_call_id="c-2", account_id=account.id, credits=1,
                    vendor_cost_micro_usd=15_000, charge_status="observed",
                    created_at=NOW),
        BillableEvent(source_idempotency_key="wb-1:1", call_id="wb-1",
                      account_id=account.id, service="llm", sku="llm_call",
                      context="agent", attempt_number=1, status="would_block",
                      quantity_json={"would_block": "credits_exhausted"},
                      event_at=NOW - timedelta(days=1)),
        ProcessedWebhook(provider="stripe", event_id="evt-err", state="error",
                         created_at=NOW - timedelta(hours=1)),
        ProcessedWebhook(provider="stripe", event_id="evt-stale", state="queued",
                         created_at=NOW - timedelta(minutes=30)),
        ProcessedWebhook(provider="stripe", event_id="evt-fresh", state="queued",
                         created_at=NOW - timedelta(minutes=1)),
        StripePayment(account_id=account.id, payment_ref="invoice:drift", kind="subscription",
                      product_key="hobby_19", pretax_amount_cents=1_900,
                      granted_credits=1_900, refunded_pretax_cents=950, clawed_credits=0),
        StripePayment(account_id=account.id, payment_ref="invoice:clean", kind="subscription",
                      product_key="hobby_19", pretax_amount_cents=1_900,
                      granted_credits=1_900, refunded_pretax_cents=950, clawed_credits=950),
        # Scheduled lot past its activation boundary.
        CreditGrant(account_id=account.id, source_type="subscription_paid",
                    source_key="ops:late-lot", original_credits=10, remaining_credits=10,
                    visible_category="paid", burn_priority=3, status="scheduled",
                    effective_at=NOW - timedelta(hours=1)),
    ])
    await _dead_job(db_session, "stripe.grant_for_invoice")
    await _dead_job(db_session, "gateway_finalize")
    await db_session.flush()

    snapshot = await ops_snapshot(db_session, now=NOW)
    assert snapshot["holds"]["open"] == {"count": 1, "credits": 5}
    assert snapshot["holds"]["needs_reconciliation"] == {"count": 1, "credits": 9}
    assert snapshot["rated_charges"]["needs_reconciliation"] == 1
    assert snapshot["would_block"]["by_code"] == {"credits_exhausted": 1}
    assert snapshot["unrated_dimensions"] == ["openai:gpt-4o:cache_write"]
    assert snapshot["worker"]["dead_money_jobs"] == 1
    assert {d["job_type"] for d in snapshot["worker"]["dead"]} == {
        "stripe.grant_for_invoice", "gateway_finalize"}
    assert snapshot["webhooks"] == {"error": 1, "stale_queued": 1, "granted_nothing": 0}
    assert snapshot["scheduled_lots"]["activation_backlog"] == 1
    assert snapshot["clawback"]["drifted_count"] == 1
    assert snapshot["clawback"]["drifted"][0]["payment_ref"] == "invoice:drift"
    assert snapshot["negative_margin_calls_7d"] == 1


@asyncio_test
async def test_payments_granted_nothing_counter(db_session, account):
    """047: a money-in outbox job that succeeded but produced no grant is the
    silent failure dead-job counters miss — the snapshot surfaces it with the
    skip reason, and it feeds a critical alert signal."""
    from cloud.billing.worker import complete_job

    paid_nothing = await enqueue(
        db_session, job_type="stripe.invoice_paid",
        payload={"event_id": "evt-skip", "object_id": "in_skip"})
    await complete_job(db_session, paid_nothing,
                       {"granted": False, "skipped": "no binding for price 'price_x'"})
    granted_ok = await enqueue(
        db_session, job_type="stripe.invoice_paid",
        payload={"event_id": "evt-ok", "object_id": "in_ok"})
    await complete_job(db_session, granted_ok, {"granted": True, "credits": 9_900})
    await db_session.flush()

    snapshot = await ops_snapshot(db_session, now=NOW)
    pgn = snapshot["payments_granted_nothing"]
    assert pgn["count"] == 1
    assert pgn["detail"][0]["event_id"] == "evt-skip"
    assert "no binding" in pgn["detail"][0]["reason"]

    signals = operations._signals(snapshot, await run_invariants(db_session))
    assert signals["payments_granted_nothing"] == 1


@asyncio_test
async def test_hosting_counters(db_session, account, sample_agent):
    await ensure_billing_account(db_session, account.id)
    starts = NOW - timedelta(days=1)
    db_session.add_all([
        AgentHostingPeriod(agent_id=sample_agent.id, account_id=account.id,
                           starts_at=starts, ends_at=starts + timedelta(days=28),
                           price_credits=999, state="pending",
                           created_at=NOW - timedelta(hours=2)),
        AgentHostingPeriod(agent_id=sample_agent.id, account_id=account.id,
                           starts_at=starts + timedelta(days=28),
                           ends_at=starts + timedelta(days=56),
                           price_credits=999, state="active",
                           charge_transaction_id=None,
                           created_at=NOW - timedelta(hours=2)),
        AgentHostingPeriod(agent_id=sample_agent.id, account_id=account.id,
                           starts_at=starts + timedelta(days=56),
                           ends_at=starts + timedelta(days=84),
                           price_credits=999, state="payment_due",
                           created_at=NOW),
    ])
    await db_session.flush()
    snapshot = await ops_snapshot(db_session, now=NOW)
    assert snapshot["hosting"] == {
        "stuck_pending": 1, "payment_due": 1, "active_without_charge": 1}


@asyncio_test
async def test_unbound_product_keys_per_mode(db_session, account):
    from cloud.billing.seed import seed_commercial_v1
    await seed_commercial_v1(db_session)
    db_session.add(StripePriceBinding(livemode=False, product_key="hobby_19",
                                      stripe_product_id="prod_x", stripe_price_id="price_x",
                                      price_usd_cents=1_900, interval="month"))
    await db_session.flush()
    snapshot = await ops_snapshot(db_session, now=NOW)
    assert "hobby_19" not in snapshot["stripe_bindings"]["test"]
    assert "hobby_19" in snapshot["stripe_bindings"]["live"]
    assert "topup_10" in snapshot["stripe_bindings"]["test"]


# ── Alert lifecycle ──────────────────────────────────────────────────────────

@asyncio_test
async def test_healthy_system_raises_no_alerts(db_session, account):
    await _funded_account(db_session, account)
    active = await evaluate_alerts(db_session, now=NOW)
    assert active == []
    assert (await db_session.execute(select(OpsAlert))).scalars().all() == []
    # Evaluation itself stamps a heartbeat.
    names = {h["name"] for h in await operations.heartbeats(db_session)}
    assert "alert_eval" in names


@asyncio_test
async def test_dead_money_job_fires_critical_then_resolves(db_session, account):
    await _funded_account(db_session, account)
    job = await _dead_job(db_session, "stripe.grant_for_invoice")

    active = await evaluate_alerts(db_session, now=NOW)
    assert [a["alert_key"] for a in active] == ["dead_money_jobs"]
    row = (await db_session.execute(
        select(OpsAlert).where(OpsAlert.alert_key == "dead_money_jobs"))).scalar_one()
    assert row.severity == "critical" and row.status == "active"
    assert row.value_json == {"value": 1}

    # Signal clears → the same row resolves; no new row is created.
    job.status = "succeeded"
    await db_session.flush()
    assert await evaluate_alerts(db_session, now=NOW + timedelta(minutes=5)) == []
    await db_session.refresh(row)
    assert row.status == "resolved" and row.resolved_at is not None
    assert len((await db_session.execute(select(OpsAlert))).scalars().all()) == 1


@asyncio_test
async def test_refire_inside_window_reuses_incident(db_session, account):
    await _funded_account(db_session, account)
    job = await _dead_job(db_session, "stripe.grant_for_invoice")
    await evaluate_alerts(db_session, now=NOW)
    row = (await db_session.execute(select(OpsAlert))).scalar_one()
    first_seen = row.first_seen_at

    job.status = "succeeded"
    await db_session.flush()
    await evaluate_alerts(db_session, now=NOW + timedelta(minutes=5))  # resolves

    # Re-fires 10 minutes later — inside the 30-minute dedupe window: the
    # incident continues (same first_seen_at), it does not restart.
    job.status = "dead"
    await db_session.flush()
    await evaluate_alerts(db_session, now=NOW + timedelta(minutes=15))
    await db_session.refresh(row)
    assert row.status == "active"
    assert row.first_seen_at == first_seen

    # Resolve again, then re-fire well past the window: a fresh incident.
    job.status = "succeeded"
    await db_session.flush()
    await evaluate_alerts(db_session, now=NOW + timedelta(minutes=20))
    job.status = "dead"
    await db_session.flush()
    await evaluate_alerts(db_session, now=NOW + timedelta(hours=2))
    await db_session.refresh(row)
    assert row.status == "active"
    assert row.first_seen_at > first_seen
    # Still exactly one row per alert key.
    assert len((await db_session.execute(select(OpsAlert))).scalars().all()) == 1


@asyncio_test
async def test_invariant_break_fires_critical_alert(db_session, account):
    await _funded_account(db_session, account)
    posting = (await db_session.execute(select(CreditLedgerPosting).limit(1))).scalar_one()
    posting.credits += 1
    await db_session.flush()
    active = await evaluate_alerts(db_session, now=NOW)
    keys = {a["alert_key"] for a in active}
    assert "trial_balance" in keys
    assert all(a["severity"] == "critical" for a in active if a["alert_key"] == "trial_balance")
