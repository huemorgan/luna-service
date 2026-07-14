"""039/008 — customer billing API: public pricing, summary, grants, usage,
statement, limits. Customer surfaces expose credits only — the tests assert
internal pricing fields never leak."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cloud.billing import ledger
from cloud.billing.grants import grant_admin_gift, grant_trial_gift
from cloud.billing.models import AgentCreditLimit, AgentLimitPeriod, BillableEvent, RatedCharge
from cloud.billing.seed import seed_billing
from cloud.db.models import Membership

pytestmark = pytest.mark.asyncio

SAME_ORIGIN = {"origin": "http://localhost:8100"}
ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")

# Strings that must never appear in any customer-facing payload.
FORBIDDEN = ("margin", "micro_usd", "llm_constants", "model_tier", "skus", "vendor_cost")


async def _seed(db_session):
    await seed_billing(db_session)
    await db_session.commit()


def _event(agent_id, call_id, *, root=None, root_type="chat", service="llm",
           plugin=None, model="claude-sonnet-5", at=None, attempt=1):
    return BillableEvent(
        source_idempotency_key=f"src:{call_id}:{attempt}",
        call_id=call_id,
        account_id=ACCOUNT_ID,
        agent_id=agent_id,
        root_action_id=root,
        root_action_type=root_type,
        plugin=plugin,
        service=service,
        sku=f"{service}.test",
        context="agent",
        model=model,
        attempt_number=attempt,
        event_at=at or datetime.now(timezone.utc),
    )


def _charge_row(call_id, credits, status="settled"):
    return RatedCharge(
        logical_call_id=call_id,
        account_id=ACCOUNT_ID,
        credits=credits,
        charge_status=status,
    )


async def _seed_usage(db_session, agent_id):
    """3 logical calls: chat with 2 attempts (charge counted once), a playbook
    child call, and a plugin call under the same playbook root."""
    await ledger.ensure_billing_account(db_session, ACCOUNT_ID)
    now = datetime.now(timezone.utc)
    db_session.add_all([
        _event(agent_id, "call-1", root="root-chat", root_type="chat", at=now - timedelta(minutes=5)),
        _event(agent_id, "call-1", root="root-chat", root_type="chat",
               at=now - timedelta(minutes=4), attempt=2),
        _event(agent_id, "call-2", root="root-pb", root_type="playbook_run",
               at=now - timedelta(minutes=3)),
        _event(agent_id, "call-3", root="root-pb", root_type="playbook_run",
               service="plugin", plugin="whatsapp", model=None, at=now - timedelta(minutes=2)),
        _charge_row("call-1", 40),
        _charge_row("call-2", 25),
        _charge_row("call-3", 10),
    ])
    await db_session.commit()


# ── Public pricing ───────────────────────────────────────────────────────────

async def test_public_pricing_unpublished_503(anon_client):
    resp = await anon_client.get("/api/public/pricing")
    assert resp.status_code == 503


async def test_public_pricing_shape_and_no_internal_leaks(anon_client, db_session):
    await _seed(db_session)
    resp = await anon_client.get("/api/public/pricing")
    assert resp.status_code == 200
    body = resp.json()

    assert body["credit_value_usd_cents"] == 1
    assert body["trial"]["gift_credits"] == 1800
    assert body["hosting"]["price_credits"] == 999
    assert body["topup_steps_usd_cents"] == [1000, 2500, 5000, 10000]

    products = {p["key"]: p for p in body["products"]}
    assert products["hobby_19"]["price_usd_cents"] == 1900
    assert products["hobby_19"]["paid_credits"] == 1900
    assert products["recurring_99"]["bonus_credits"] == 1100
    assert products["recurring_199_yearly"]["interval"] == "year"
    # Yearly gift = two months of the package's paid monthly credits.
    assert products["recurring_99_yearly"]["yearly_gift_credits"] == 19800

    text = resp.text.lower()
    for token in FORBIDDEN:
        assert token not in text, f"internal field {token!r} leaked to public pricing"


# ── Auth boundaries ──────────────────────────────────────────────────────────

async def test_billing_endpoints_require_auth(anon_client):
    for path in ("/api/billing/summary", "/api/billing/grants", "/api/billing/products",
                 "/api/billing/usage/summary", "/api/billing/usage/breakdown",
                 "/api/billing/usage/actions", "/api/billing/statement"):
        assert (await anon_client.get(path)).status_code == 401, path


# ── Summary ──────────────────────────────────────────────────────────────────

async def test_summary_trial_balances_and_payments_flag(admin_client, db_session, account):
    await _seed(db_session)
    await grant_trial_gift(db_session, account.id)
    await db_session.commit()

    resp = await admin_client.get("/api/billing/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["posted_balance_credits"] == 1800
    assert body["balances"]["gift"] == 1800
    assert body["trial"]["is_trial"] is True
    assert body["trial"]["expires_at"] is not None
    assert body["trial"]["active_luna_cap"] == 1
    assert body["payments_enabled"] is False
    assert body["recovery"]["debt_credits"] == 0
    assert body["recovery"]["payment_action_required"] is False

    text = resp.text.lower()
    for token in FORBIDDEN:
        assert token not in text, f"internal field {token!r} leaked to summary"


async def test_summary_paid_grant_ends_trial(admin_client, db_session, account):
    await _seed(db_session)
    await ledger.create_grant(
        db_session, account_id=account.id, source_type="topup",
        source_key=f"test-topup:{account.id}", credits=1000,
        visible_category="topup", effective_at=datetime.now(timezone.utc),
        expires_at=None, cash_paid_micro_usd=10_000_000,
    )
    await db_session.commit()
    body = (await admin_client.get("/api/billing/summary")).json()
    assert body["trial"]["is_trial"] is False
    assert body["balances"]["topup"] == 1000


# ── Grants ───────────────────────────────────────────────────────────────────

async def test_grants_burn_order(admin_client, db_session, account):
    await _seed(db_session)
    await grant_trial_gift(db_session, account.id)
    await ledger.create_grant(
        db_session, account_id=account.id, source_type="subscription_paid",
        source_key=f"test-paid:{account.id}", credits=500,
        visible_category="paid", effective_at=datetime.now(timezone.utc),
        expires_at=None, cash_paid_micro_usd=5_000_000,
    )
    await db_session.commit()

    rows = (await admin_client.get("/api/billing/grants")).json()
    assert len(rows) == 2
    by_cat = {r["category"]: r for r in rows}
    # Gift burns before paid (burn priority), so it is "use next" #1.
    assert by_cat["gift"]["use_next_order"] == 1
    assert by_cat["paid"]["use_next_order"] == 2
    assert by_cat["gift"]["remaining_credits"] == 1800


# ── Products ─────────────────────────────────────────────────────────────────

async def test_products_payments_disabled(admin_client, db_session):
    await _seed(db_session)
    body = (await admin_client.get("/api/billing/products")).json()
    assert body["payments_enabled"] is False
    assert {p["key"] for p in body["products"]} >= {"hobby_19", "recurring_99", "recurring_199"}


# ── Usage ────────────────────────────────────────────────────────────────────

async def test_usage_summary_totals_and_per_luna(admin_client, db_session, account, sample_agent):
    await _seed(db_session)
    await grant_trial_gift(db_session, account.id)
    await _seed_usage(db_session, sample_agent.id)
    now = datetime.now(timezone.utc)
    db_session.add(AgentCreditLimit(agent_id=sample_agent.id, daily_limit_credits=75,
                                    monthly_limit_credits=800, warning_threshold_pct=80))
    db_session.add(AgentLimitPeriod(
        agent_id=sample_agent.id, period_kind="daily",
        period_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
        period_end=now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
        settled_credits=70, open_exposure_credits=5,
    ))
    await db_session.commit()

    body = (await admin_client.get("/api/billing/usage/summary?range=7d")).json()
    assert body["used_credits"] == 75  # 40 + 25 + 10
    assert body["today_credits"] == 75
    assert len(body["trend"]) == 1
    assert body["trend"][0]["credits"] == 75
    assert body["projection_is_estimate"] is True

    luna = body["per_luna"][0]
    assert luna["agent_name"] == "Test Agent"
    assert luna["daily"]["used_credits"] == 75  # settled + open exposure
    assert luna["daily"]["limit_credits"] == 75
    assert luna["warning_threshold_pct"] == 80


async def test_usage_range_validation(admin_client, db_session):
    await _seed(db_session)
    assert (await admin_client.get("/api/billing/usage/summary?range=bogus")).status_code == 400
    assert (await admin_client.get("/api/billing/usage/summary?range=custom")).status_code == 400
    assert (
        await admin_client.get(
            "/api/billing/usage/summary?range=custom"
            "&start=2026-01-01T00:00:00%2B00:00&end=2027-06-01T00:00:00%2B00:00"
        )
    ).status_code == 400  # > 366 days


async def test_usage_breakdown_dimensions(admin_client, db_session, account, sample_agent):
    await _seed(db_session)
    await _seed_usage(db_session, sample_agent.id)

    rows = (await admin_client.get("/api/billing/usage/breakdown?by=agent&range=7d")).json()
    assert rows[0]["key"] == "Test Agent"
    assert rows[0]["credits"] == 75

    rows = (await admin_client.get("/api/billing/usage/breakdown?by=action_type&range=7d")).json()
    by_key = {r["key"]: r["credits"] for r in rows}
    assert by_key == {"chat": 40, "playbook_run": 35}

    rows = (await admin_client.get("/api/billing/usage/breakdown?by=plugin&range=7d")).json()
    by_key = {r["key"]: r["credits"] for r in rows}
    assert by_key["whatsapp"] == 10

    assert (await admin_client.get("/api/billing/usage/breakdown?by=sku")).status_code == 400


async def test_breakdown_keeps_tombstoned_agent_names(admin_client, db_session, account, sample_agent):
    await _seed(db_session)
    await _seed_usage(db_session, sample_agent.id)
    sample_agent.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    rows = (await admin_client.get("/api/billing/usage/breakdown?by=agent&range=7d")).json()
    assert rows[0]["key"] == "Test Agent"  # history keeps the name after delete


async def test_usage_actions_grouping_and_csv(admin_client, db_session, account, sample_agent):
    await _seed(db_session)
    await _seed_usage(db_session, sample_agent.id)

    rows = (await admin_client.get("/api/billing/usage/actions?range=7d")).json()
    by_root = {r["root_action_id"]: r for r in rows}
    # call-1 has 2 attempts/events but its 40-credit charge counts once.
    assert by_root["root-chat"]["credits"] == 40
    assert by_root["root-chat"]["label"] == "Chat"
    # The playbook root groups two calls: 25 + 10.
    assert by_root["root-pb"]["credits"] == 35
    assert len(by_root["root-pb"]["children"]) == 2
    assert by_root["root-pb"]["label"] == "Playbook run"

    resp = await admin_client.get("/api/billing/usage/actions.csv?range=7d")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    lines = resp.text.strip().splitlines()
    assert lines[0] == "time,luna,action,service,status,credits"
    assert len(lines) == 3  # two roots + header

    text = resp.text.lower() + str(rows).lower()
    for token in FORBIDDEN:
        assert token not in text, f"internal field {token!r} leaked to actions"


# ── Statement ────────────────────────────────────────────────────────────────

async def test_statement_running_balance(admin_client, db_session, account):
    await _seed(db_session)
    await grant_admin_gift(db_session, account.id, credits=1000, expires_days=None,
                           source_key=f"test-gift:{account.id}", actor="test", reason="seed")
    await ledger.charge(db_session, account_id=account.id, idempotency_key="c1",
                        credits=100, service="llm", reason="chat")
    await ledger.charge(db_session, account_id=account.id, idempotency_key="c2",
                        credits=50, service="llm", reason="chat")
    await db_session.commit()

    rows = (await admin_client.get("/api/billing/statement")).json()
    assert [r["credits"] for r in rows] == [-50, -100, 1000]  # newest first
    assert [r["balance_after"] for r in rows] == [850, 900, 1000]
    assert rows[0]["type"] == "charge"
    assert rows[2]["type"] == "grant"


# ── Limits ───────────────────────────────────────────────────────────────────

async def test_limits_owner_can_set(admin_client, db_session, account, sample_agent):
    await _seed(db_session)
    resp = await admin_client.put(
        f"/api/billing/limits/{sample_agent.id}",
        json={"daily_limit_credits": 100, "monthly_limit_credits": 900,
              "warning_threshold_pct": 75},
        headers=SAME_ORIGIN,
    )
    assert resp.status_code == 200
    lim = await db_session.get(AgentCreditLimit, sample_agent.id)
    assert (lim.daily_limit_credits, lim.monthly_limit_credits, lim.warning_threshold_pct) == (100, 900, 75)

    # Clearing limits: nulls are legal (no limit).
    resp = await admin_client.put(
        f"/api/billing/limits/{sample_agent.id}", json={}, headers=SAME_ORIGIN,
    )
    assert resp.status_code == 200
    await db_session.refresh(lim)
    assert lim.daily_limit_credits is None


async def test_limits_member_forbidden(regular_client, regular_user, db_session, account, sample_agent):
    await _seed(db_session)
    db_session.add(Membership(account_id=account.id, user_id=regular_user.id, role="member"))
    await db_session.commit()

    resp = await regular_client.put(
        f"/api/billing/limits/{sample_agent.id}",
        json={"daily_limit_credits": 10}, headers=SAME_ORIGIN,
    )
    assert resp.status_code == 403


async def test_limits_cross_origin_rejected(admin_client, db_session, account, sample_agent):
    await _seed(db_session)
    resp = await admin_client.put(
        f"/api/billing/limits/{sample_agent.id}",
        json={"daily_limit_credits": 10},
        headers={"origin": "https://evil.example"},
    )
    assert resp.status_code == 403


async def test_limits_unknown_or_deleted_agent_404(admin_client, db_session, account, sample_agent):
    await _seed(db_session)
    resp = await admin_client.put(
        f"/api/billing/limits/{uuid.uuid4()}", json={}, headers=SAME_ORIGIN,
    )
    assert resp.status_code == 404

    sample_agent.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()
    resp = await admin_client.put(
        f"/api/billing/limits/{sample_agent.id}", json={}, headers=SAME_ORIGIN,
    )
    assert resp.status_code == 404
