"""Per-account enforcement override resolution (039/010)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cloud.billing import hosting, ledger, modes
from cloud.billing.models import AgentHostingPeriod, BillingAccount
from cloud.billing.seed import seed_billing

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


# ── combine ──────────────────────────────────────────────────────────────────

async def test_combine_is_max_of_the_two():
    assert modes.combine("off", None) == "off"
    assert modes.combine("off", "observe") == "observe"
    assert modes.combine("off", "enforce") == "enforce"
    assert modes.combine("observe", "shadow") == "shadow"
    assert modes.combine("shadow", "observe") == "shadow"   # never lowers
    assert modes.combine("enforce", "observe") == "enforce"  # never lowers
    assert modes.combine("enforce", None) == "enforce"
    assert modes.combine("shadow", "shadow") == "shadow"


# ── set/clear + resolution ───────────────────────────────────────────────────

async def test_set_override_and_effective_mode(db_session, account):
    assert await modes.effective_mode(db_session, account.id, "off") == "off"

    row = await modes.set_override(db_session, account.id, "enforce")
    await db_session.commit()
    assert row.enforcement_override == "enforce"
    assert row.enforcement_override_set_at is not None
    assert await modes.effective_mode(db_session, account.id, "off") == "enforce"
    assert await modes.effective_mode(db_session, account.id, "enforce") == "enforce"

    row = await modes.set_override(db_session, account.id, None)
    await db_session.commit()
    assert row.enforcement_override is None
    assert await modes.effective_mode(db_session, account.id, "off") == "off"


async def test_set_override_rejects_off_and_garbage(db_session, account):
    with pytest.raises(ValueError):
        await modes.set_override(db_session, account.id, "off")
    with pytest.raises(ValueError):
        await modes.set_override(db_session, account.id, "everything")


async def test_override_map_caches_and_invalidates(db_session, account):
    assert await modes.override_map(db_session) == {}

    # Write behind the cache's back: the stale empty map is served until
    # invalidation (set_override invalidates automatically; raw writes don't).
    ba = await ledger.ensure_billing_account(db_session, account.id)
    ba.enforcement_override = "shadow"
    await db_session.commit()
    assert await modes.override_map(db_session) == {}

    modes.invalidate_override_cache()
    assert await modes.override_map(db_session) == {account.id: "shadow"}


# ── hosting integration ──────────────────────────────────────────────────────

async def test_hosting_enforced_by_override_while_global_off(db_session, account):
    assert not await hosting.hosting_enforced(db_session, account.id)
    await modes.set_override(db_session, account.id, "enforce")
    await db_session.commit()
    assert await hosting.hosting_enforced(db_session, account.id)


async def test_hosting_blocked_respects_override(db_session, account, sample_agent):
    await seed_billing(db_session)
    await ledger.ensure_billing_account(db_session, account.id)
    db_session.add(AgentHostingPeriod(
        agent_id=sample_agent.id,
        account_id=account.id,
        starts_at=NOW - timedelta(days=40),
        ends_at=NOW - timedelta(days=10),
        price_credits=999,
        state="payment_due",
    ))
    await db_session.commit()

    # Global off, no override: the payment_due period does not block.
    assert not await hosting.hosting_blocked(db_session, sample_agent.id)

    await modes.set_override(db_session, account.id, "enforce")
    await db_session.commit()
    assert await hosting.hosting_blocked(db_session, sample_agent.id)

    # shadow never blocks — only effective enforce does.
    await modes.set_override(db_session, account.id, "shadow")
    await db_session.commit()
    assert not await hosting.hosting_blocked(db_session, sample_agent.id)


async def test_hosting_blocked_unknown_agent_is_false(db_session):
    assert not await hosting.hosting_blocked(db_session, uuid.uuid4())


async def test_check_constraint_rejects_bad_override_value(db_session, account):
    from sqlalchemy.exc import IntegrityError

    await ledger.ensure_billing_account(db_session, account.id)
    await db_session.execute(
        select(BillingAccount).where(BillingAccount.account_id == account.id)
    )
    ba = await db_session.get(BillingAccount, account.id)
    ba.enforcement_override = "wat"
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
