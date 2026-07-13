"""039/001 — double-entry ledger: grants, burn order, debt, holds, limits."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from cloud.billing import ledger
from cloud.billing.ledger import (
    CONSUMED,
    DEBT,
    WALLET,
    BillingError,
    IdempotencyConflict,
    InsufficientBalance,
    LimitExceeded,
    UnbalancedPostings,
    activate_scheduled_grants,
    authorize,
    canonical_request_hash,
    charge,
    create_grant,
    ensure_billing_account,
    expire_due_grants,
    mark_stale_holds,
    post_transaction,
    posted_balance,
    rebuild_projection,
    release,
    reverse_transaction,
    settle,
)
from cloud.billing.models import (
    AccountBalanceProjection,
    AgentCreditLimit,
    CreditConsumption,
    CreditGrant,
    CreditLedgerPosting,
)


NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)

_SOURCE_FOR_CATEGORY = {
    "paid": "subscription_paid",
    "bonus": "subscription_bonus",
    "gift": "gift",
    "free": "free_recurring",
    "topup": "topup",
}


async def _grant(db, account, credits=100, key=None, category="gift", effective=None,
                 expires=None, now=None):
    return await create_grant(
        db,
        account_id=account.id,
        source_type=_SOURCE_FOR_CATEGORY[category],
        source_key=key or f"test:{uuid.uuid4()}",
        credits=credits,
        visible_category=category,
        effective_at=effective or NOW,
        expires_at=expires,
        now=now or NOW,
    )


async def _wallet(db, account_id):
    return await posted_balance(db, account_id)


# ── Posting engine ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unbalanced_postings_rejected(db_session, account):
    await ensure_billing_account(db_session, account.id)
    with pytest.raises(UnbalancedPostings):
        await post_transaction(
            db_session, type="grant", idempotency_key="x", request_hash="h",
            account_id=account.id, postings=[(WALLET, 100)],
        )
    with pytest.raises(UnbalancedPostings):
        await post_transaction(
            db_session, type="grant", idempotency_key="x", request_hash="h",
            account_id=account.id, postings=[],
        )
    with pytest.raises(UnbalancedPostings):
        await post_transaction(
            db_session, type="grant", idempotency_key="x", request_hash="h",
            account_id=account.id, postings=[(WALLET, 1.0), ("y", -1)],  # type: ignore[list-item]
        )


@pytest.mark.asyncio
async def test_grant_posts_balanced_and_idempotent(db_session, account):
    grant = await _grant(db_session, account, credits=500, key="gift:1")
    assert grant.status == "active"
    assert await _wallet(db_session, account.id) == 500
    # Same source_key again → same lot, no double posting.
    again = await _grant(db_session, account, credits=500, key="gift:1")
    assert again.id == grant.id
    assert await _wallet(db_session, account.id) == 500
    total = (
        await db_session.execute(select(func.sum(CreditLedgerPosting.credits)))
    ).scalar_one()
    assert total == 0


@pytest.mark.asyncio
async def test_charge_idempotency_and_conflict(db_session, account):
    await _grant(db_session, account, credits=100)
    t1 = await charge(db_session, account_id=account.id, idempotency_key="op:1", credits=30, now=NOW)
    t2 = await charge(db_session, account_id=account.id, idempotency_key="op:1", credits=30, now=NOW)
    assert t1.id == t2.id
    assert await _wallet(db_session, account.id) == 70
    with pytest.raises(IdempotencyConflict):
        await charge(db_session, account_id=account.id, idempotency_key="op:1", credits=31, now=NOW)


# ── Burn order ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_burn_order_category_then_expiry(db_session, account):
    late = NOW + timedelta(days=60)
    soon = NOW + timedelta(days=10)
    paid = await _grant(db_session, account, 100, "paid:1", "paid", expires=soon)
    topup = await _grant(db_session, account, 100, "topup:1", "topup")
    gift_late = await _grant(db_session, account, 100, "gift:late", "gift", expires=late)
    gift_soon = await _grant(db_session, account, 100, "gift:soon", "gift", expires=soon)
    bonus = await _grant(db_session, account, 100, "bonus:1", "bonus", expires=late)

    txn = await charge(db_session, account_id=account.id, idempotency_key="op:burn", credits=250, now=NOW)
    rows = (
        await db_session.execute(
            select(CreditConsumption).where(CreditConsumption.charge_transaction_id == txn.id)
        )
    ).scalars().all()
    burned = {r.grant_id: r.credits for r in rows}
    # bonus first, then gifts by earliest expiry, paid untouched until gifts gone.
    assert burned == {bonus.id: 100, gift_soon.id: 100, gift_late.id: 50}
    assert paid.remaining_credits == 100
    assert topup.remaining_credits == 100
    assert bonus.status == "exhausted"


@pytest.mark.asyncio
async def test_non_expiring_topup_burns_last(db_session, account):
    topup = await _grant(db_session, account, 100, "topup:1", "topup")
    paid = await _grant(db_session, account, 100, "paid:1", "paid", expires=NOW + timedelta(days=30))
    await charge(db_session, account_id=account.id, idempotency_key="op:1", credits=150, now=NOW)
    assert paid.remaining_credits == 0
    assert topup.remaining_credits == 50


# ── Debt (5 → charge 10 → −5) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_charge_posts_fully_into_debt(db_session, account):
    await _grant(db_session, account, credits=5, key="gift:small")
    txn = await charge(db_session, account_id=account.id, idempotency_key="op:big", credits=10, now=NOW)
    assert await _wallet(db_session, account.id) == -5
    rows = (
        await db_session.execute(
            select(CreditConsumption).where(CreditConsumption.charge_transaction_id == txn.id)
        )
    ).scalars().all()
    covered = sum(r.credits for r in rows if r.grant_id is not None)
    uncovered = [r for r in rows if r.grant_id is None]
    assert covered == 5
    assert len(uncovered) == 1 and uncovered[0].credits == 5
    projection = await db_session.get(AccountBalanceProjection, account.id)
    assert projection.posted_balance_credits == -5
    assert projection.debt_credits == 5


@pytest.mark.asyncio
async def test_next_grant_repays_debt_without_double_wallet_movement(db_session, account):
    await _grant(db_session, account, credits=5, key="gift:small")
    await charge(db_session, account_id=account.id, idempotency_key="op:big", credits=10, now=NOW)
    grant = await _grant(db_session, account, credits=100, key="topup:pay", category="topup")
    # Wallet: -5 + 100 = 95. Debt repaid inside the grant, not by re-charging.
    assert await _wallet(db_session, account.id) == 95
    assert grant.remaining_credits == 95
    debt = (
        await db_session.execute(
            select(func.coalesce(func.sum(CreditLedgerPosting.credits), 0)).where(
                CreditLedgerPosting.account_id == account.id,
                CreditLedgerPosting.ledger_account == DEBT,
            )
        )
    ).scalar_one()
    assert debt == 0
    projection = await db_session.get(AccountBalanceProjection, account.id)
    assert projection.debt_credits == 0
    assert projection.posted_balance_credits == 95


# ── Expiration ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_expiration_exclusive_boundary(db_session, account):
    expiry = NOW + timedelta(days=10)
    await _grant(db_session, account, 100, "gift:exp", expires=expiry)
    await charge(db_session, account_id=account.id, idempotency_key="op:1", credits=30, now=NOW)
    txns = await expire_due_grants(db_session, account.id, now=expiry)  # exact boundary expires
    assert len(txns) == 1
    assert await _wallet(db_session, account.id) == 0
    projection = await db_session.get(AccountBalanceProjection, account.id)
    assert projection.gift_credits == 0
    assert projection.next_expiry_at is None


@pytest.mark.asyncio
async def test_expired_grant_never_burns(db_session, account):
    await _grant(db_session, account, 100, "gift:exp", expires=NOW + timedelta(days=1))
    with pytest.raises(InsufficientBalance):
        await authorize(
            db_session, operation_id="op:late", account_id=account.id,
            estimated_credits=10, now=NOW + timedelta(days=2),
        )


# ── Scheduled lots ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheduled_grant_posts_only_at_activation(db_session, account):
    grant = await _grant(
        db_session, account, 100, "paid:sched", "paid",
        effective=NOW + timedelta(days=30), now=NOW,
    )
    assert grant.status == "scheduled"
    assert await _wallet(db_session, account.id) == 0
    activated = await activate_scheduled_grants(db_session, account.id, now=NOW + timedelta(days=30))
    assert [g.id for g in activated] == [grant.id]
    assert await _wallet(db_session, account.id) == 100


@pytest.mark.asyncio
async def test_scheduled_grant_expired_before_activation_posts_nothing(db_session, account):
    grant = await _grant(
        db_session, account, 100, "paid:sched", "paid",
        effective=NOW + timedelta(days=30), expires=NOW + timedelta(days=40), now=NOW,
    )
    await activate_scheduled_grants(db_session, account.id, now=NOW + timedelta(days=50))
    assert grant.status == "expired"
    assert await _wallet(db_session, account.id) == 0
    # Expiry sweep must not post an expiration for a never-posted lot either.
    txns = await expire_due_grants(db_session, account.id, now=NOW + timedelta(days=50))
    assert txns == []


# ── Reversal ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reverse_charge_restores_grants(db_session, account):
    grant = await _grant(db_session, account, 100, "gift:1")
    txn = await charge(db_session, account_id=account.id, idempotency_key="op:1", credits=100, now=NOW)
    assert grant.status == "exhausted"
    rev = await reverse_transaction(
        db_session, transaction_id=txn.id, reason="support refund", actor="admin"
    )
    assert rev.reversal_of_id == txn.id
    assert grant.status == "active" and grant.remaining_credits == 100
    assert await _wallet(db_session, account.id) == 100
    # Idempotent.
    rev2 = await reverse_transaction(
        db_session, transaction_id=txn.id, reason="support refund", actor="admin"
    )
    assert rev2.id == rev.id
    with pytest.raises(BillingError):
        await reverse_transaction(db_session, transaction_id=rev.id, reason="no", actor="admin")


@pytest.mark.asyncio
async def test_reverse_charge_cancels_uncovered_debt(db_session, account):
    await _grant(db_session, account, 5, "gift:small")
    txn = await charge(db_session, account_id=account.id, idempotency_key="op:1", credits=10, now=NOW)
    await reverse_transaction(db_session, transaction_id=txn.id, reason="refund", actor="admin")
    assert await _wallet(db_session, account.id) == 5
    # A later grant must not "repay" the cancelled debt.
    grant = await _grant(db_session, account, 100, "topup:1", "topup")
    assert grant.remaining_credits == 100


@pytest.mark.asyncio
async def test_reverse_grant_only_when_unconsumed(db_session, account):
    grant = await _grant(db_session, account, 100, "gift:1")
    txn_id = grant.grant_transaction_id
    await charge(db_session, account_id=account.id, idempotency_key="op:1", credits=10, now=NOW)
    with pytest.raises(BillingError, match="clawback"):
        await reverse_transaction(db_session, transaction_id=txn_id, reason="oops", actor="admin")

    fresh = await _grant(db_session, account, 50, "gift:2")
    rev = await reverse_transaction(
        db_session, transaction_id=fresh.grant_transaction_id, reason="mistake", actor="admin"
    )
    assert rev is not None
    assert fresh.status == "reversed" and fresh.remaining_credits == 0
    assert await _wallet(db_session, account.id) == 90


# ── Projection ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_projection_matches_ledger_replay(db_session, account):
    await _grant(db_session, account, 100, "gift:1", "gift", expires=NOW + timedelta(days=30))
    await _grant(db_session, account, 200, "paid:1", "paid", expires=NOW + timedelta(days=60))
    await _grant(db_session, account, 50, "topup:1", "topup")
    await charge(db_session, account_id=account.id, idempotency_key="op:1", credits=120, now=NOW)
    projection = await rebuild_projection(db_session, account.id)
    assert projection.posted_balance_credits == 230
    assert projection.gift_credits == 0       # burned first (only expiring categories here)
    assert projection.paid_credits == 180
    assert projection.topup_credits == 50
    assert projection.debt_credits == 0
    assert projection.next_expiry_at == NOW + timedelta(days=60)
    assert projection.posted_balance_credits == await _wallet(db_session, account.id)


# ── Authorize / settle / release ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authorize_blocked_at_zero_balance(db_session, account):
    await ensure_billing_account(db_session, account.id)
    with pytest.raises(InsufficientBalance):
        await authorize(db_session, operation_id="op:1", account_id=account.id,
                        estimated_credits=10, now=NOW)


@pytest.mark.asyncio
async def test_authorize_idempotent_and_conflict(db_session, account):
    await _grant(db_session, account, 100, "gift:1")
    h1 = await authorize(db_session, operation_id="op:1", account_id=account.id,
                         estimated_credits=10, now=NOW)
    h2 = await authorize(db_session, operation_id="op:1", account_id=account.id,
                         estimated_credits=10, now=NOW)
    assert h1.id == h2.id
    with pytest.raises(IdempotencyConflict):
        await authorize(db_session, operation_id="op:1", account_id=account.id,
                        estimated_credits=11, now=NOW)


@pytest.mark.asyncio
async def test_single_bounded_overrun(db_session, account):
    await _grant(db_session, account, 100, "gift:1")
    # Overrun within cap (default 1000) is allowed once.
    await authorize(db_session, operation_id="op:1", account_id=account.id,
                    estimated_credits=600, now=NOW)
    # Second overrun while one is in flight → blocked (available is 100-600<0).
    with pytest.raises(LimitExceeded) as exc:
        await authorize(db_session, operation_id="op:2", account_id=account.id,
                        estimated_credits=10, now=NOW)
    assert exc.value.code == "exposure_limit"


@pytest.mark.asyncio
async def test_overrun_cap_enforced(db_session, account):
    acct = await ensure_billing_account(db_session, account.id)
    acct.overrun_cap_credits = 50
    await _grant(db_session, account, 100, "gift:1")
    with pytest.raises(LimitExceeded):
        await authorize(db_session, operation_id="op:1", account_id=account.id,
                        estimated_credits=200, now=NOW)  # overrun 100 > cap 50
    hold = await authorize(db_session, operation_id="op:2", account_id=account.id,
                           estimated_credits=140, now=NOW)  # overrun 40 <= 50
    assert hold.overrun_credits == 40


@pytest.mark.asyncio
async def test_concurrent_holds_within_balance(db_session, account):
    await _grant(db_session, account, 100, "gift:1")
    await authorize(db_session, operation_id="op:1", account_id=account.id,
                    estimated_credits=60, now=NOW)
    await authorize(db_session, operation_id="op:2", account_id=account.id,
                    estimated_credits=40, now=NOW)  # exactly exhausts availability
    with pytest.raises(LimitExceeded):
        await authorize(db_session, operation_id="op:3", account_id=account.id,
                        estimated_credits=1, now=NOW)


@pytest.mark.asyncio
async def test_settle_release_lifecycle(db_session, account):
    await _grant(db_session, account, 100, "gift:1")
    await authorize(db_session, operation_id="op:1", account_id=account.id,
                    estimated_credits=50, now=NOW)
    txn = await settle(db_session, operation_id="op:1", final_credits=30, now=NOW)
    txn2 = await settle(db_session, operation_id="op:1", final_credits=30, now=NOW)
    assert txn.id == txn2.id
    assert await _wallet(db_session, account.id) == 70

    await authorize(db_session, operation_id="op:2", account_id=account.id,
                    estimated_credits=50, now=NOW)
    hold = await release(db_session, operation_id="op:2", now=NOW)
    assert hold.status == "released"
    assert await _wallet(db_session, account.id) == 70
    projection = await db_session.get(AccountBalanceProjection, account.id)
    assert projection.open_exposure_credits == 0


@pytest.mark.asyncio
async def test_stale_holds_keep_bounding_exposure(db_session, account):
    acct = await ensure_billing_account(db_session, account.id)
    acct.overrun_cap_credits = 0  # so exceeding availability blocks outright
    await _grant(db_session, account, 100, "gift:1")
    await authorize(db_session, operation_id="op:1", account_id=account.id,
                    estimated_credits=80, now=NOW, ttl=timedelta(minutes=5))
    stale = await mark_stale_holds(db_session, now=NOW + timedelta(minutes=10))
    assert len(stale) == 1 and stale[0].status == "needs_reconciliation"
    projection = await db_session.get(AccountBalanceProjection, account.id)
    assert projection.open_exposure_credits == 80
    # The unresolved hold still consumes availability.
    with pytest.raises(LimitExceeded):
        await authorize(db_session, operation_id="op:2", account_id=account.id,
                        estimated_credits=30, now=NOW + timedelta(minutes=10))
    # Settling a needs_reconciliation hold is allowed (reconciliation path).
    await settle(db_session, operation_id="op:1", final_credits=20,
                 now=NOW + timedelta(minutes=15))
    projection = await db_session.get(AccountBalanceProjection, account.id)
    assert projection.open_exposure_credits == 0


# ── Agent limits ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_daily_and_monthly_limits(db_session, account, sample_agent):
    await _grant(db_session, account, 10_000, "topup:1", "topup")
    db_session.add(AgentCreditLimit(agent_id=sample_agent.id,
                                    daily_limit_credits=100, monthly_limit_credits=150))
    await db_session.flush()

    await authorize(db_session, operation_id="op:1", account_id=account.id,
                    agent_id=sample_agent.id, estimated_credits=80, now=NOW)
    with pytest.raises(LimitExceeded) as exc:
        await authorize(db_session, operation_id="op:2", account_id=account.id,
                        agent_id=sample_agent.id, estimated_credits=30, now=NOW)
    assert exc.value.code == "luna_daily_limit"

    # Next UTC day: daily resets, monthly still accumulates.
    await settle(db_session, operation_id="op:1", final_credits=80, now=NOW)
    day2 = NOW + timedelta(days=1)
    with pytest.raises(LimitExceeded) as exc:
        await authorize(db_session, operation_id="op:3", account_id=account.id,
                        agent_id=sample_agent.id, estimated_credits=80, now=day2)
    assert exc.value.code == "luna_monthly_limit"
    hold = await authorize(db_session, operation_id="op:4", account_id=account.id,
                           agent_id=sample_agent.id, estimated_credits=70, now=day2)
    assert hold.estimated_credits == 70


@pytest.mark.asyncio
async def test_hosting_excluded_from_limits(db_session, account, sample_agent):
    await _grant(db_session, account, 10_000, "topup:1", "topup")
    db_session.add(AgentCreditLimit(agent_id=sample_agent.id, daily_limit_credits=100))
    await db_session.flush()
    hold = await authorize(
        db_session, operation_id="op:hosting", account_id=account.id,
        agent_id=sample_agent.id, estimated_credits=999, service="hosting",
        count_toward_limits=False, now=NOW,
    )
    assert hold is not None
    # Regular work still has the full daily allowance.
    await authorize(db_session, operation_id="op:2", account_id=account.id,
                    agent_id=sample_agent.id, estimated_credits=100, now=NOW)


@pytest.mark.asyncio
async def test_release_drains_limit_exposure(db_session, account, sample_agent):
    await _grant(db_session, account, 10_000, "topup:1", "topup")
    db_session.add(AgentCreditLimit(agent_id=sample_agent.id, daily_limit_credits=100))
    await db_session.flush()
    await authorize(db_session, operation_id="op:1", account_id=account.id,
                    agent_id=sample_agent.id, estimated_credits=100, now=NOW)
    await release(db_session, operation_id="op:1", now=NOW)
    hold = await authorize(db_session, operation_id="op:2", account_id=account.id,
                           agent_id=sample_agent.id, estimated_credits=100, now=NOW)
    assert hold is not None


# ── Hash canon ───────────────────────────────────────────────────────────────

def test_canonical_request_hash_is_order_insensitive():
    assert canonical_request_hash({"a": 1, "b": 2}) == canonical_request_hash({"b": 2, "a": 1})
    assert canonical_request_hash({"a": 1}) != canonical_request_hash({"a": 2})
