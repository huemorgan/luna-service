"""Existing-account migration: dry-run manifest + idempotent execution (039/010)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from cloud.billing import ledger, migration
from cloud.billing.models import (
    AgentCreditLimit,
    AgentHostingPeriod,
    BillingJob,
    CreditGrant,
)
from cloud.billing.seed import seed_billing
from cloud.db.models import Account, Agent, AuditLog, User

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
CUTOVER = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)


async def _mk_account(db, user, slug, created_at):
    acc = Account(slug=slug, name=slug.title(), created_by=user.id, created_at=created_at)
    db.add(acc)
    await db.flush()
    await ledger.ensure_billing_account(db, acc.id)
    return acc


def _mk_agent(db, user, account, slug, status, last_active_at=None, created_at=None):
    agent = Agent(
        account_id=account.id, creator_id=user.id, name=slug, slug=slug,
        status=status, last_active_at=last_active_at,
        created_at=created_at or (NOW - timedelta(days=100)),
    )
    db.add(agent)
    return agent


@pytest_asyncio.fixture
async def cohort(db_session, admin_user):
    """Three pre-cutover accounts + one post-cutover:
    - alpha: two running Lunas (one recently active) + one stopped
    - beta:  one stopped Luna only
    - gamma: no Lunas at all
    - delta: created AFTER the cutover — must be excluded
    """
    await seed_billing(db_session)
    alpha = await _mk_account(db_session, admin_user, "alpha", NOW - timedelta(days=200))
    beta = await _mk_account(db_session, admin_user, "beta", NOW - timedelta(days=150))
    gamma = await _mk_account(db_session, admin_user, "gamma", NOW - timedelta(days=90))
    delta = await _mk_account(db_session, admin_user, "delta", CUTOVER + timedelta(days=1))

    keep = _mk_agent(db_session, admin_user, alpha, "alpha-keep", "running",
                     last_active_at=NOW - timedelta(hours=1))
    stop = _mk_agent(db_session, admin_user, alpha, "alpha-stop", "running",
                     last_active_at=NOW - timedelta(days=30))
    _mk_agent(db_session, admin_user, alpha, "alpha-idle", "stopped")
    _mk_agent(db_session, admin_user, beta, "beta-idle", "stopped")
    _mk_agent(db_session, admin_user, delta, "delta-run", "running")
    await db_session.commit()
    return {"alpha": alpha, "beta": beta, "gamma": gamma, "delta": delta,
            "keep": keep, "stop": stop}


async def test_plan_manifest_shape_and_determinism(db_session, cohort):
    m1 = await migration.plan_migration(db_session, cutover_at=CUTOVER, now=NOW)
    m2 = await migration.plan_migration(db_session, cutover_at=CUTOVER, now=NOW)
    assert m1["content_hash"] == m2["content_hash"]

    assert m1["totals"] == {
        "accounts": 3,               # delta excluded by the cutover boundary
        "already_migrated": 0,
        "pending": 3,
        "running_lunas": 2,
        "not_running_lunas": 2,
        "keeps": 1,
        "stops": 1,
        "gift_credits_total": 3 * 1_800,
        "hosting_charges_total": 999,
        "accounts_without_assignment": 3,  # no explicit assignments seeded
        "resulting_liability_credits": 3 * 1_800 - 999,
    }
    by_slug = {e["slug"]: e for e in m1["per_account"]}
    assert by_slug["alpha"]["keep_agent_id"] == str(cohort["keep"].id)
    assert by_slug["alpha"]["stop_agent_ids"] == [str(cohort["stop"].id)]
    assert by_slug["alpha"]["hosting_charge_credits"] == 999
    assert by_slug["beta"]["keep_agent_id"] is None
    assert by_slug["beta"]["hosting_charge_credits"] == 0
    assert by_slug["gamma"]["agents_total"] == 0
    assert "delta" not in by_slug


async def test_plan_cohort_filter(db_session, cohort):
    m = await migration.plan_migration(
        db_session, cutover_at=CUTOVER, account_ids=[cohort["beta"].id], now=NOW
    )
    assert [e["slug"] for e in m["per_account"]] == ["beta"]


async def test_execute_posts_gift_hosting_stops_and_audit(db_session, cohort):
    manifest = await migration.plan_migration(db_session, cutover_at=CUTOVER, now=NOW)
    result = await migration.execute_migration(
        db_session, manifest=manifest, actor="test", now=NOW
    )
    assert result["totals"] == {
        "applied": 3, "replayed": 0,
        "gift_credits_posted": 5_400,
        "hosting_charges_posted": 999,
        "stop_jobs_enqueued": 1,
    }

    alpha, beta = cohort["alpha"], cohort["beta"]
    # Gifts, idempotent source keys.
    grants = (await db_session.execute(select(CreditGrant))).scalars().all()
    assert {g.source_key for g in grants} == {
        migration.gift_source_key(alpha.id),
        migration.gift_source_key(beta.id),
        migration.gift_source_key(cohort["gamma"].id),
    }
    assert all(g.source_type == "gift" and g.original_credits == 1_800 for g in grants)
    # SQLite round-trips timestamptz naive — normalize before comparing.
    assert all(
        g.expires_at.replace(tzinfo=timezone.utc) == NOW + timedelta(days=28)
        for g in grants
    )

    # Kept Luna: first hosting period active, charged 999 → balance 801.
    periods = (await db_session.execute(select(AgentHostingPeriod))).scalars().all()
    assert len(periods) == 1
    assert periods[0].agent_id == cohort["keep"].id
    assert periods[0].state == "active"
    assert periods[0].charge_transaction_id is not None
    assert await ledger.posted_balance(db_session, alpha.id) == 1_800 - 999
    assert await ledger.posted_balance(db_session, beta.id) == 1_800

    # Kept Luna got insert-only trial limits from config.
    assert await db_session.get(AgentCreditLimit, cohort["keep"].id) is not None

    # The other running Luna gets a durable stop job — never a delete.
    jobs = (await db_session.execute(select(BillingJob))).scalars().all()
    stop_jobs = [j for j in jobs if j.job_type == "hosting_suspend"]
    assert len(stop_jobs) == 1
    assert stop_jobs[0].payload == {"agent_id": str(cohort["stop"].id)}
    assert stop_jobs[0].dedupe_key == migration.stop_dedupe_key(cohort["stop"].id)

    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "billing.migration.account")
    )).scalars().all()
    assert len(audits) == 3


async def test_execute_rerun_replays_without_new_rows(db_session, cohort):
    manifest = await migration.plan_migration(db_session, cutover_at=CUTOVER, now=NOW)
    await migration.execute_migration(db_session, manifest=manifest, actor="test", now=NOW)

    # State legitimately moves after migration (worker stops Lunas, users act);
    # the rerun must replay from the grants, not re-compare drifted state.
    cohort["stop"].status = "stopped"
    await db_session.commit()

    again = await migration.execute_migration(
        db_session, manifest=manifest, actor="test", now=NOW + timedelta(hours=1)
    )
    assert again["totals"]["applied"] == 0
    assert again["totals"]["replayed"] == 3
    grants = (await db_session.execute(select(CreditGrant))).scalars().all()
    assert len(grants) == 3
    periods = (await db_session.execute(select(AgentHostingPeriod))).scalars().all()
    assert len(periods) == 1


async def test_execute_aborts_on_drift_with_zero_writes(db_session, cohort):
    alpha_id = str(cohort["alpha"].id)  # before rollback expires the instances
    manifest = await migration.plan_migration(db_session, cutover_at=CUTOVER, now=NOW)

    # Live state drifts between dry run and execution: the keep Luna stopped.
    cohort["keep"].status = "stopped"
    await db_session.commit()

    with pytest.raises(migration.MigrationMismatch) as exc:
        await migration.execute_migration(db_session, manifest=manifest, actor="test", now=NOW)
    await db_session.rollback()
    assert any(m["account_id"] == alpha_id for m in exc.value.mismatches)

    assert (await db_session.execute(select(CreditGrant))).scalars().all() == []
    assert (await db_session.execute(select(AgentHostingPeriod))).scalars().all() == []
    assert (await db_session.execute(select(BillingJob))).scalars().all() == []


async def test_execute_rejects_tampered_manifest(db_session, cohort):
    manifest = await migration.plan_migration(db_session, cutover_at=CUTOVER, now=NOW)
    manifest["totals"]["gift_credits_total"] = 1  # edited after review
    with pytest.raises(migration.MigrationMismatch):
        await migration.execute_migration(db_session, manifest=manifest, actor="test", now=NOW)
    assert (await db_session.execute(select(CreditGrant))).scalars().all() == []


async def test_keep_selection_most_recent_activity_wins(db_session, admin_user):
    """Recency key is (last_active_at or created_at) — so a fresh never-used
    running Luna beats an older one whose last activity predates the creation."""
    await seed_billing(db_session)
    acc = await _mk_account(db_session, admin_user, "sel", NOW - timedelta(days=60))
    active_now = _mk_agent(db_session, admin_user, acc, "sel-a", "running",
                           last_active_at=NOW - timedelta(hours=1),
                           created_at=NOW - timedelta(days=50))
    _mk_agent(db_session, admin_user, acc, "sel-b", "running",
              last_active_at=NOW - timedelta(days=2),
              created_at=NOW - timedelta(days=40))
    await db_session.commit()

    m = await migration.plan_migration(
        db_session, cutover_at=CUTOVER, account_ids=[acc.id], now=NOW
    )
    assert m["per_account"][0]["keep_agent_id"] == str(active_now.id)
