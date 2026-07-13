"""039/005 — grants, hosting periods, limits: trial gift, active-Luna cap,
durable provisioning, monthly-anchor renewal, payment_due + recovery,
soft delete, maintenance sweeps, admin gifts."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cloud.billing import grants, hosting, ledger, maintenance, rating
from cloud.billing.models import (
    AgentCreditLimit,
    AgentHostingPeriod,
    BillingHold,
    BillingJob,
    CreditGrant,
    CreditLedgerTransaction,
    ResourceAllocation,
)
from cloud.billing.seed import seed_billing
from cloud.db.models import Agent

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
JAN31 = datetime(2026, 1, 31, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_rating_caches():
    rating.invalidate_rating_caches()
    yield
    rating.invalidate_rating_caches()


def _set_mode(monkeypatch, mode: str):
    # One switch for hosting + agent_routes + proxy guard: they all resolve
    # the mode through cloud.billing.hosting.billing_mode.
    monkeypatch.setattr("cloud.billing.hosting.billing_mode", lambda: mode)


async def _seed(db, account_id):
    await seed_billing(db)
    await ledger.ensure_billing_account(db, account_id)
    await db.commit()


async def _fund(db, account_id, credits, *, now=NOW):
    await ledger.create_grant(
        db, account_id=account_id, source_type="gift",
        source_key=f"fund:{uuid.uuid4()}", credits=credits,
        visible_category="gift", effective_at=now - timedelta(days=1),
        expires_at=None, now=now,
    )


async def _job(db, dedupe_key) -> BillingJob:
    return (await db.execute(
        select(BillingJob).where(BillingJob.dedupe_key == dedupe_key)
    )).scalar_one()


# ── Month math ───────────────────────────────────────────────────────────────

async def test_add_month_clamped_short_months():
    feb = hosting.add_month_clamped(31, JAN31)
    assert (feb.month, feb.day) == (2, 28)  # 2026 is not a leap year
    mar = hosting.add_month_clamped(31, feb)
    assert (mar.month, mar.day) == (3, 31)  # returns to the anchor day


async def test_add_month_clamped_leap_and_year_wrap():
    dec = datetime(2027, 12, 31, tzinfo=timezone.utc)
    jan = hosting.add_month_clamped(31, dec)
    assert (jan.year, jan.month, jan.day) == (2028, 1, 31)
    feb = hosting.add_month_clamped(31, jan)
    assert (feb.month, feb.day) == (2, 29)  # 2028 is a leap year


# ── Trial gift + trial detection ─────────────────────────────────────────────

async def test_trial_gift_exactly_once(db_session, account):
    await _seed(db_session, account.id)
    g1 = await grants.grant_trial_gift(db_session, account.id, now=NOW)
    g2 = await grants.grant_trial_gift(db_session, account.id, now=NOW)
    assert g1.id == g2.id  # source_key trial:{account} dedupes
    lots = (await db_session.execute(
        select(CreditGrant).where(CreditGrant.account_id == account.id)
    )).scalars().all()
    assert len(lots) == 1
    assert lots[0].original_credits == 1800
    assert lots[0].source_type == "gift" and lots[0].visible_category == "gift"
    assert lots[0].expires_at == NOW + timedelta(days=28)
    assert await ledger.posted_balance(db_session, account.id) == 1800


async def test_trial_flips_to_paid_on_topup(db_session, account):
    await _seed(db_session, account.id)
    await grants.grant_trial_gift(db_session, account.id, now=NOW)
    assert await grants.is_trial_account(db_session, account.id) is True
    await ledger.create_grant(
        db_session, account_id=account.id, source_type="topup",
        source_key="stripe:pi_1", credits=500, visible_category="topup",
        effective_at=NOW, expires_at=None, now=NOW,
    )
    assert await grants.is_trial_account(db_session, account.id) is False


async def test_apply_trial_agent_limits_insert_only(db_session, account, sample_agent):
    await _seed(db_session, account.id)
    config = await grants.account_config(db_session, account.id, NOW)
    row = await grants.apply_trial_agent_limits(db_session, sample_agent.id, config)
    assert row.daily_limit_credits == 75 and row.monthly_limit_credits == 800
    row.daily_limit_credits = 10  # customer-edited
    again = await grants.apply_trial_agent_limits(db_session, sample_agent.id, config)
    assert again.daily_limit_credits == 10  # never overwritten


# ── start_hosting ────────────────────────────────────────────────────────────

async def test_start_hosting_enforce_needs_balance(db_session, account, sample_agent, monkeypatch):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    with pytest.raises(hosting.HostingError) as exc:
        await hosting.start_hosting(
            db_session, agent_id=sample_agent.id, account_id=account.id, now=NOW
        )
    assert exc.value.code == "credits_exhausted"
    assert (await db_session.execute(select(AgentHostingPeriod))).scalars().all() == []


async def test_start_hosting_enforce_hold_job_idempotent(db_session, account, sample_agent, monkeypatch):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 1800)
    p1 = await hosting.start_hosting(
        db_session, agent_id=sample_agent.id, account_id=account.id, now=NOW
    )
    p2 = await hosting.start_hosting(
        db_session, agent_id=sample_agent.id, account_id=account.id, now=NOW
    )
    assert p1.id == p2.id and p1.state == "pending"
    assert p1.price_credits == 999
    assert p1.ends_at == hosting.add_month_clamped(NOW.day, NOW)
    hold = (await db_session.execute(select(BillingHold))).scalar_one()
    assert hold.operation_id == f"hosting:{p1.id}"
    assert hold.estimated_credits == 999 and hold.status == "open"
    await _job(db_session, f"hostprov:{p1.id}")  # provisioning enqueued


async def test_start_hosting_observe_no_money_movement(db_session, account, sample_agent, monkeypatch):
    _set_mode(monkeypatch, "observe")
    await _seed(db_session, account.id)  # empty wallet is fine outside enforce
    period = await hosting.start_hosting(
        db_session, agent_id=sample_agent.id, account_id=account.id, now=NOW
    )
    assert period.state == "pending"
    assert (await db_session.execute(select(BillingHold))).scalars().all() == []
    await _job(db_session, f"hostprov:{period.id}")


async def test_hosting_hold_ignores_per_luna_limits(db_session, account, sample_agent, monkeypatch):
    # A 999 hosting hold must pass even under a 75/day Luna limit.
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 1800)
    db_session.add(AgentCreditLimit(
        agent_id=sample_agent.id, daily_limit_credits=75, monthly_limit_credits=800,
    ))
    await db_session.flush()
    period = await hosting.start_hosting(
        db_session, agent_id=sample_agent.id, account_id=account.id, now=NOW
    )
    assert period.state == "pending"  # no LimitExceeded


# ── Provisioning handler ─────────────────────────────────────────────────────

def _fake_provision(db_session, agent, *, status="running"):
    async def fake(account_id, agent_id=None, **kwargs):
        row = await db_session.get(Agent, uuid.UUID(agent_id))
        row.status = status
        await db_session.flush()
        return row
    return fake


async def _start_and_get_job(db_session, account, agent, *, now=NOW):
    period = await hosting.start_hosting(
        db_session, agent_id=agent.id, account_id=account.id, now=now
    )
    await db_session.commit()
    job = await _job(db_session, f"hostprov:{period.id}")
    return period, job


async def test_provision_handler_settles_and_activates(
    db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 1800)
    period, job = await _start_and_get_job(db_session, account, sample_agent)
    monkeypatch.setattr(
        "cloud.provisioning.workflow.provision_luna_for_account",
        _fake_provision(db_session, sample_agent),
    )

    result = await hosting._handle_hosting_provision(db_session, job)
    assert result["state"] == "active"
    await db_session.commit()

    period = await db_session.get(AgentHostingPeriod, period.id)
    assert period.state == "active"
    hold = (await db_session.execute(select(BillingHold))).scalar_one()
    assert hold.status == "settled"
    assert period.charge_transaction_id is not None
    assert await ledger.posted_balance(db_session, account.id) == 1800 - 999

    # Machine + volume allocations exist, included in hosting — never priced.
    allocs = (await db_session.execute(select(ResourceAllocation))).scalars().all()
    assert allocs and all(a.sku is None for a in allocs)
    assert all(a.dimensions["included_in"] == "hosting_month" for a in allocs)
    assert period.resource_allocation_id in {a.id for a in allocs}

    # Crash-retry: a second run is a no-op, no double charge.
    result = await hosting._handle_hosting_provision(db_session, job)
    assert "skipped" in result
    assert await ledger.posted_balance(db_session, account.id) == 1800 - 999


async def test_provision_handler_failure_leaves_hold_for_reaper(
    db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 1800)
    period, job = await _start_and_get_job(db_session, account, sample_agent)
    monkeypatch.setattr(
        "cloud.provisioning.workflow.provision_luna_for_account",
        _fake_provision(db_session, sample_agent, status="error"),
    )
    with pytest.raises(RuntimeError):
        await hosting._handle_hosting_provision(db_session, job)
    period = await db_session.get(AgentHostingPeriod, period.id)
    assert period.state == "pending"
    hold = (await db_session.execute(select(BillingHold))).scalar_one()
    assert hold.status == "open"  # reaper's problem after TTL, never silently released


async def test_provision_handler_reaped_hold_still_settles(
    db_session, account, sample_agent, monkeypatch,
):
    # Slow provision: the reaper already flagged the hold. settle() accepts
    # needs_reconciliation holds, so the charge still posts normally.
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 1800)
    period, job = await _start_and_get_job(db_session, account, sample_agent)
    hold = (await db_session.execute(select(BillingHold))).scalar_one()
    hold.status = "needs_reconciliation"
    await db_session.flush()
    monkeypatch.setattr(
        "cloud.provisioning.workflow.provision_luna_for_account",
        _fake_provision(db_session, sample_agent),
    )
    result = await hosting._handle_hosting_provision(db_session, job)
    assert result["state"] == "active"
    period = await db_session.get(AgentHostingPeriod, period.id)
    assert period.state == "active"
    assert period.charge_transaction_id is not None
    assert await ledger.posted_balance(db_session, account.id) == 1800 - 999


async def test_provision_handler_missing_hold_activates_without_charge(
    db_session, account, sample_agent, monkeypatch,
):
    # Mode flipped observe → enforce between creation and the handler run:
    # there is no hold to settle. The customer has the machine — activate the
    # period, log for ops; retrying the job would never make settle succeed.
    _set_mode(monkeypatch, "observe")
    await _seed(db_session, account.id)
    period, job = await _start_and_get_job(db_session, account, sample_agent)
    _set_mode(monkeypatch, "enforce")
    monkeypatch.setattr(
        "cloud.provisioning.workflow.provision_luna_for_account",
        _fake_provision(db_session, sample_agent),
    )
    result = await hosting._handle_hosting_provision(db_session, job)
    assert result["state"] == "active"
    period = await db_session.get(AgentHostingPeriod, period.id)
    assert period.state == "active"
    assert period.charge_transaction_id is None


async def test_provision_handler_agent_deleted_releases_hold(
    db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 1800)
    period, job = await _start_and_get_job(db_session, account, sample_agent)
    sample_agent.deleted_at = NOW
    await db_session.flush()
    result = await hosting._handle_hosting_provision(db_session, job)
    assert "skipped" in result
    period = await db_session.get(AgentHostingPeriod, period.id)
    assert period.state == "stopped"
    hold = (await db_session.execute(select(BillingHold))).scalar_one()
    assert hold.status == "released"
    assert await ledger.posted_balance(db_session, account.id) == 1800


# ── Renewal ──────────────────────────────────────────────────────────────────

async def _active_period(db_session, account, agent, *, starts, version_id, price=999):
    period = AgentHostingPeriod(
        agent_id=agent.id, account_id=account.id,
        starts_at=starts, ends_at=hosting.add_month_clamped(starts.day, starts),
        price_credits=price, commercial_pricing_version_id=version_id,
        state="active",
    )
    db_session.add(period)
    await db_session.flush()
    return period


async def test_renewal_monthly_anchor_clamp(db_session, account, sample_agent, monkeypatch):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 5000, now=JAN31)
    version_id, _ = await rating.resolve_commercial_version(db_session, account.id, JAN31)
    first = await _active_period(
        db_session, account, sample_agent, starts=JAN31, version_id=version_id
    )
    assert (first.ends_at.month, first.ends_at.day) == (2, 28)

    renewed = await hosting.renew_due_periods(db_session, now=first.ends_at)
    assert len(renewed) == 1
    second = renewed[0]
    assert second.starts_at == first.ends_at  # seamless, no gap
    assert (second.ends_at.month, second.ends_at.day) == (3, 31)  # anchor restored
    assert (await db_session.get(AgentHostingPeriod, first.id)).state == "ended"
    assert second.charge_transaction_id is not None
    assert await ledger.posted_balance(db_session, account.id) == 5000 - 999

    # Sweep is idempotent: nothing else due at the same instant.
    assert await hosting.renew_due_periods(db_session, now=first.ends_at) == []


async def test_renewal_unpayable_payment_due_suspend_and_recovery(
    db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    version_id, _ = await rating.resolve_commercial_version(db_session, account.id, JAN31)
    period = await _active_period(
        db_session, account, sample_agent, starts=JAN31, version_id=version_id
    )

    due_at = period.ends_at
    assert await hosting.renew_due_periods(db_session, now=due_at) == []  # empty wallet
    period = await db_session.get(AgentHostingPeriod, period.id)
    assert period.state == "payment_due"
    await _job(db_session, f"hostsusp:{period.id}")  # durable suspend queued

    # Guard: blocked in enforce, invisible outside it.
    assert await hosting.hosting_blocked(db_session, sample_agent.id) is True
    _set_mode(monkeypatch, "observe")
    assert await hosting.hosting_blocked(db_session, sample_agent.id) is False
    _set_mode(monkeypatch, "enforce")

    # Recovery fails while broke, succeeds once funded — fresh month charged.
    assert await hosting.try_recover_payment_due(db_session, sample_agent, now=due_at) is False
    await _fund(db_session, account.id, 1200, now=due_at)
    assert await hosting.try_recover_payment_due(db_session, sample_agent, now=due_at) is True
    assert await hosting.hosting_blocked(db_session, sample_agent.id) is False
    assert await ledger.posted_balance(db_session, account.id) == 1200 - 999
    fresh = (await db_session.execute(
        select(AgentHostingPeriod).where(AgentHostingPeriod.state == "active")
    )).scalar_one()
    assert (fresh.ends_at.month, fresh.ends_at.day) == (3, 31)  # anchor kept


async def test_renewal_observe_rolls_period_without_charge(
    db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "observe")
    await _seed(db_session, account.id)
    version_id, _ = await rating.resolve_commercial_version(db_session, account.id, JAN31)
    period = await _active_period(
        db_session, account, sample_agent, starts=JAN31, version_id=version_id
    )
    [renewed] = await hosting.renew_due_periods(db_session, now=period.ends_at)
    assert renewed.charge_transaction_id is None
    assert (await db_session.execute(select(CreditLedgerTransaction))).scalars().all() == []


async def test_renewal_of_deleted_agent_just_ends(db_session, account, sample_agent, monkeypatch):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    version_id, _ = await rating.resolve_commercial_version(db_session, account.id, JAN31)
    period = await _active_period(
        db_session, account, sample_agent, starts=JAN31, version_id=version_id
    )
    sample_agent.deleted_at = JAN31
    await db_session.flush()
    assert await hosting.renew_due_periods(db_session, now=period.ends_at) == []
    assert (await db_session.get(AgentHostingPeriod, period.id)).state == "ended"


# ── Maintenance sweeps ───────────────────────────────────────────────────────

async def test_maintenance_expires_trial_gift(db_session, account):
    await _seed(db_session, account.id)
    await grants.grant_trial_gift(db_session, account.id, now=NOW)
    assert await ledger.posted_balance(db_session, account.id) == 1800

    after = NOW + timedelta(days=28)
    counts = await maintenance.maintenance_once(db_session, now=after)
    assert counts["expired"] == 1
    assert await ledger.posted_balance(db_session, account.id) == 0
    # Rerun-safe: append-only expiry never fires twice.
    counts = await maintenance.maintenance_once(db_session, now=after)
    assert counts["expired"] == 0


# ── Routes: create / start / destroy / wake ──────────────────────────────────

async def test_create_agent_trial_cap_enforced(
    admin_client, db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 5000)
    await db_session.commit()
    r = await admin_client.post("/api/agents", json={"name": "Second Luna"})
    assert r.status_code == 402
    assert r.json()["detail"]["code"] == "active_luna_limit"


async def test_create_agent_trial_cap_observe_only_logs(
    admin_client, db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "observe")
    await _seed(db_session, account.id)
    await db_session.commit()
    r = await admin_client.post("/api/agents", json={"name": "Second Luna"})
    assert r.status_code == 201  # would_block, never blocked outside enforce


async def test_create_agent_enforce_broke_402_no_agent_row(
    admin_client, db_session, account, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await db_session.commit()
    r = await admin_client.post("/api/agents", json={"name": "First Luna"})
    assert r.status_code == 402
    assert r.json()["detail"]["code"] == "credits_exhausted"
    assert (await db_session.execute(select(Agent))).scalars().all() == []


async def test_create_agent_enforce_funded_durable_provisioning(
    admin_client, db_session, account, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 1800)
    await db_session.commit()
    r = await admin_client.post("/api/agents", json={"name": "First Luna"})
    assert r.status_code == 201
    agent_id = uuid.UUID(r.json()["id"])
    period = (await db_session.execute(
        select(AgentHostingPeriod).where(AgentHostingPeriod.agent_id == agent_id)
    )).scalar_one()
    assert period.state == "pending"
    await _job(db_session, f"hostprov:{period.id}")
    limits = await db_session.get(AgentCreditLimit, agent_id)
    assert limits.daily_limit_credits == 75 and limits.monthly_limit_credits == 800


async def test_start_agent_payment_due_402(
    admin_client, db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    version_id, _ = await rating.resolve_commercial_version(db_session, account.id, JAN31)
    period = await _active_period(
        db_session, account, sample_agent, starts=JAN31, version_id=version_id
    )
    period.state = "payment_due"
    sample_agent.status = "stopped"
    await db_session.commit()
    r = await admin_client.post(f"/api/agents/{sample_agent.id}/start")
    assert r.status_code == 402
    assert r.json()["detail"]["code"] == "hosting_payment_due"


async def test_destroy_agent_soft_deletes_and_keeps_billing(
    admin_client, db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    await _fund(db_session, account.id, 1800)
    version_id, _ = await rating.resolve_commercial_version(db_session, account.id, NOW)
    period = await _active_period(
        db_session, account, sample_agent, starts=NOW, version_id=version_id
    )
    txn = await ledger.charge(
        db_session, account_id=account.id, idempotency_key=f"hosting_renew:{period.id}",
        credits=999, agent_id=sample_agent.id, service="hosting", now=NOW,
    )
    period.charge_transaction_id = txn.id
    await db_session.commit()

    r = await admin_client.delete(f"/api/agents/{sample_agent.id}")
    assert r.status_code == 200

    # The route committed in its own session; refresh past our identity map.
    await db_session.refresh(sample_agent)
    await db_session.refresh(period)
    assert sample_agent.deleted_at is not None  # tombstone, not gone
    assert sample_agent.status == "stopped"
    assert period.state == "ended"
    # The paid charge stands — early deletion forfeits the month remainder.
    assert await ledger.posted_balance(db_session, account.id) == 1800 - 999
    await _job(db_session, f"teardown:{sample_agent.id}")

    # Gone from the user-facing surface.
    r = await admin_client.get("/api/agents")
    assert r.json() == []
    r = await admin_client.get(f"/api/agents/{sample_agent.id}")
    assert r.status_code == 404


async def test_teardown_handler_destroys_runtime_and_closes_allocations(
    db_session, account, sample_agent, monkeypatch,
):
    destroyed = []

    class FakeRuntime:
        async def destroy(self, handle):
            destroyed.append(handle)

    monkeypatch.setattr("cloud.provisioning.workflow._get_runtime", FakeRuntime)
    db_session.add(ResourceAllocation(
        agent_id=sample_agent.id, account_id=account.id, resource_kind="machine",
        provider="fly-machine", provider_resource_id="machine-123",
        dimensions={}, opened_at=NOW, reconcile_state="confirmed",
    ))
    sample_agent.deleted_at = NOW
    job = BillingJob(job_type=hosting.TEARDOWN_JOB,
                     payload={"agent_id": str(sample_agent.id)})
    db_session.add(job)
    await db_session.flush()

    result = await hosting._handle_agent_teardown(db_session, job)
    assert result == {"torn_down": str(sample_agent.id)}
    assert len(destroyed) == 1
    assert destroyed[0].extra["volume_id"] == sample_agent.volume_id
    agent = await db_session.get(Agent, sample_agent.id)
    assert agent.runtime_ref is None and agent.internal_url is None
    alloc = (await db_session.execute(select(ResourceAllocation))).scalar_one()
    assert alloc.closed_at is not None and alloc.reconcile_state == "closed"


async def test_wake_blocked_while_payment_due(
    _patch_db, db_session, account, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed(db_session, account.id)
    version_id, _ = await rating.resolve_commercial_version(db_session, account.id, JAN31)
    period = await _active_period(
        db_session, account, sample_agent, starts=JAN31, version_id=version_id
    )
    period.state = "payment_due"
    await db_session.commit()

    monkeypatch.setenv("FLY_API_TOKEN", "fake-token")
    from cloud.api.proxy import _try_wake_agent
    assert await _try_wake_agent(sample_agent) is False


# ── Admin gifts ──────────────────────────────────────────────────────────────

async def test_admin_gift_requires_reason(admin_client, db_session, account):
    await _seed(db_session, account.id)
    r = await admin_client.post("/api/admin/pricing/gifts", json={
        "account_id": str(account.id), "credits": 500,
    })
    assert r.status_code == 400


async def test_admin_gift_creates_lot_with_default_expiry(
    admin_client, db_session, account,
):
    await _seed(db_session, account.id)
    r = await admin_client.post("/api/admin/pricing/gifts", json={
        "account_id": str(account.id), "credits": 500,
        "reason": "goodwill for the outage",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["credits"] == 500
    assert body["expires_at"] is not None  # config gift_default_days = 90
    assert await ledger.posted_balance(db_session, account.id) == 500

    # Same idempotency key → same lot, no double credit.
    r2 = await admin_client.post("/api/admin/pricing/gifts", json={
        "account_id": str(account.id), "credits": 500,
        "idempotency_key": body["source_key"], "reason": "retry",
    })
    assert r2.status_code == 200
    assert r2.json()["grant_id"] == body["grant_id"]
    assert await ledger.posted_balance(db_session, account.id) == 500


async def test_admin_gift_forbidden_for_regular_user(regular_client, db_session, account):
    await _seed(db_session, account.id)
    r = await regular_client.post("/api/admin/pricing/gifts", json={
        "account_id": str(account.id), "credits": 500, "reason": "nope",
    })
    assert r.status_code == 403
