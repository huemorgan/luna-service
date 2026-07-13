"""Double-entry credit ledger: grants, charges, burn order, holds, limits.

Posting conventions (credits, sum per transaction is always zero):
- grant:          customer_wallet +N,  grant_issuance:{source} -N
- charge:         customer_wallet -C,  credits_consumed +covered, uncovered_debt +uncovered
- expiration:     customer_wallet -R,  credits_expired +R
- debt repayment: uncovered_debt -X,   credits_consumed +X   (no wallet movement)
- reversal:       exact negation of the original postings

The posted wallet balance is the sum of `customer_wallet` postings. Every
mutation happens under the account's `billing_accounts` row lock, in the
caller's database transaction (callers commit; nothing here commits).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing.models import (
    AccountBalanceProjection,
    AgentCreditLimit,
    AgentLimitPeriod,
    BillingAccount,
    BillingHold,
    CreditConsumption,
    CreditGrant,
    CreditLedgerPosting,
    CreditLedgerTransaction,
)

WALLET = "customer_wallet"
CONSUMED = "credits_consumed"
DEBT = "uncovered_debt"
EXPIRED = "credits_expired"
ADJUSTMENT = "manual_adjustment"

# Burn order: recurring bonus → gifts/free by earliest expiry → recurring paid
# by earliest expiry → non-expiring top-ups oldest first.
BURN_PRIORITY = {"bonus": 1, "gift": 2, "free": 2, "paid": 3, "topup": 4}

DEFAULT_HOLD_TTL = timedelta(minutes=30)


class BillingError(Exception):
    code = "billing_error"


class IdempotencyConflict(BillingError):
    """Same operation ID reused with a different request payload."""
    code = "idempotency_conflict"


class InsufficientBalance(BillingError):
    code = "credits_exhausted"


class LimitExceeded(BillingError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class UnbalancedPostings(BillingError):
    code = "unbalanced_postings"


def canonical_request_hash(payload: dict) -> str:
    """Canonical hash of a financial request; pairs with an operation ID to
    make every mutation idempotent."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """DB-loaded timestamps are naive UTC on SQLite and aware on Postgres;
    normalize before any in-Python comparison."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Account + locking ────────────────────────────────────────────────────────

async def ensure_billing_account(session: AsyncSession, account_id: uuid.UUID) -> BillingAccount:
    acct = await session.get(BillingAccount, account_id)
    if acct is None:
        acct = BillingAccount(account_id=account_id)
        session.add(acct)
        await session.flush()
        session.add(AccountBalanceProjection(account_id=account_id))
        await session.flush()
    return acct


async def lock_billing_account(session: AsyncSession, account_id: uuid.UUID) -> BillingAccount:
    """Row-lock the billing account (serializes financial mutations).
    FOR UPDATE is a no-op on SQLite, where tests are single-connection."""
    result = await session.execute(
        select(BillingAccount).where(BillingAccount.account_id == account_id).with_for_update()
    )
    acct = result.scalar_one_or_none()
    if acct is None:
        return await ensure_billing_account(session, account_id)
    return acct


# ── Posting engine ───────────────────────────────────────────────────────────

async def find_transaction(session: AsyncSession, idempotency_key: str) -> CreditLedgerTransaction | None:
    result = await session.execute(
        select(CreditLedgerTransaction).where(
            CreditLedgerTransaction.idempotency_key == idempotency_key
        )
    )
    return result.scalar_one_or_none()


async def post_transaction(
    session: AsyncSession,
    *,
    type: str,
    idempotency_key: str,
    request_hash: str,
    account_id: uuid.UUID,
    postings: list[tuple[str, int]],
    agent_id: uuid.UUID | None = None,
    root_action_id: str | None = None,
    service: str | None = None,
    source_ref: str | None = None,
    reversal_of_id: uuid.UUID | None = None,
    commercial_pricing_version_id: uuid.UUID | None = None,
    provider_cost_version_id: uuid.UUID | None = None,
    reason: str | None = None,
    actor: str | None = None,
    metadata: dict | None = None,
) -> tuple[CreditLedgerTransaction, bool]:
    """Insert a balanced transaction (header + postings atomically in the
    caller's DB transaction). Returns (transaction, created).

    Same idempotency key + same hash → the original transaction; same key with
    a different hash → IdempotencyConflict.
    """
    existing = await find_transaction(session, idempotency_key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict(idempotency_key)
        return existing, False

    if not postings:
        raise UnbalancedPostings("a transaction requires postings")
    for _, credits in postings:
        if not isinstance(credits, int) or isinstance(credits, bool):
            raise UnbalancedPostings("posting credits must be int")
    if sum(c for _, c in postings) != 0:
        raise UnbalancedPostings(f"postings sum to {sum(c for _, c in postings)}, not zero")

    txn = CreditLedgerTransaction(
        type=type,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        account_id=account_id,
        agent_id=agent_id,
        root_action_id=root_action_id,
        service=service,
        source_ref=source_ref,
        reversal_of_id=reversal_of_id,
        commercial_pricing_version_id=commercial_pricing_version_id,
        provider_cost_version_id=provider_cost_version_id,
        reason=reason,
        actor=actor,
        metadata_=metadata,
    )
    session.add(txn)
    await session.flush()  # header + postings flush inside one DB transaction
    for ledger_account, credits in postings:
        session.add(
            CreditLedgerPosting(
                transaction_id=txn.id,
                ledger_account=ledger_account,
                account_id=account_id,
                credits=credits,
            )
        )
    await session.flush()
    return txn, True


# ── Grants ───────────────────────────────────────────────────────────────────

async def create_grant(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    source_type: str,
    source_key: str,
    credits: int,
    visible_category: str,
    effective_at: datetime,
    expires_at: datetime | None,
    cash_paid_micro_usd: int = 0,
    stripe_ref: str | None = None,
    actor: str | None = None,
    reason: str | None = None,
    now: datetime | None = None,
) -> CreditGrant:
    """Create a grant lot idempotently (by source_key). Future-effective
    grants are `scheduled` and post to the wallet only at activation.
    Effective grants post immediately and then repay outstanding debt."""
    if not isinstance(credits, int) or isinstance(credits, bool) or credits <= 0:
        raise BillingError("grant credits must be a positive int")
    if visible_category not in BURN_PRIORITY:
        raise BillingError(f"unknown grant category {visible_category!r}")
    now = now or _utcnow()

    await lock_billing_account(session, account_id)

    existing = await session.execute(select(CreditGrant).where(CreditGrant.source_key == source_key))
    grant = existing.scalar_one_or_none()
    if grant is not None:
        return grant

    scheduled = effective_at > now
    grant = CreditGrant(
        account_id=account_id,
        source_type=source_type,
        source_key=source_key,
        original_credits=credits,
        remaining_credits=credits,
        effective_at=effective_at,
        expires_at=expires_at,
        visible_category=visible_category,
        burn_priority=BURN_PRIORITY[visible_category],
        stripe_ref=stripe_ref,
        cash_paid_micro_usd=cash_paid_micro_usd,
        status="scheduled" if scheduled else "active",
    )
    session.add(grant)
    await session.flush()
    if not scheduled:
        await _post_grant_activation(session, grant, actor=actor, reason=reason)
        await rebuild_projection(session, account_id)
    return grant


async def _post_grant_activation(
    session: AsyncSession, grant: CreditGrant, *, actor: str | None, reason: str | None
) -> CreditLedgerTransaction:
    """Post the wallet movement for a grant lot and repay debt from it."""
    payload = {"grant": grant.source_key, "credits": grant.original_credits}
    txn, created = await post_transaction(
        session,
        type="grant",
        idempotency_key=f"grant:{grant.source_key}",
        request_hash=canonical_request_hash(payload),
        account_id=grant.account_id,
        postings=[
            (WALLET, grant.original_credits),
            (f"grant_issuance:{grant.source_type}", -grant.original_credits),
        ],
        source_ref=grant.source_key,
        actor=actor,
        reason=reason,
    )
    if created:
        grant.grant_transaction_id = txn.id
        await _repay_debt_from_grant(session, grant, actor=actor)
    return txn


async def activate_scheduled_grants(
    session: AsyncSession, account_id: uuid.UUID, now: datetime | None = None
) -> list[CreditGrant]:
    """Activate scheduled lots whose effective time has arrived. Lots already
    past their expiry expire without ever posting."""
    now = now or _utcnow()
    result = await session.execute(
        select(CreditGrant)
        .where(
            CreditGrant.account_id == account_id,
            CreditGrant.status == "scheduled",
            CreditGrant.effective_at <= now,
        )
        .order_by(CreditGrant.effective_at.asc())
    )
    activated: list[CreditGrant] = []
    for grant in result.scalars().all():
        if grant.expires_at is not None and _aware(grant.expires_at) <= now:
            grant.status = "expired"
            grant.remaining_credits = 0
            continue
        grant.status = "active"
        await _post_grant_activation(session, grant, actor="system", reason="scheduled activation")
        activated.append(grant)
    if activated:
        await rebuild_projection(session, account_id)
    return activated


async def _outstanding_debt_rows(session: AsyncSession, account_id: uuid.UUID) -> list[CreditConsumption]:
    result = await session.execute(
        select(CreditConsumption)
        .where(
            CreditConsumption.account_id == account_id,
            CreditConsumption.grant_id.is_(None),
            CreditConsumption.credits > CreditConsumption.repaid_credits,
        )
        .order_by(CreditConsumption.created_at.asc(), CreditConsumption.id.asc())
    )
    return list(result.scalars().all())


async def _repay_debt_from_grant(
    session: AsyncSession, grant: CreditGrant, *, actor: str | None
) -> int:
    """Allocate a newly posted grant to prior uncovered consumptions:
    uncovered_debt → credits_consumed, no second wallet movement."""
    debt_rows = await _outstanding_debt_rows(session, grant.account_id)
    repayable = sum(r.credits - r.repaid_credits for r in debt_rows)
    repay = min(grant.remaining_credits, repayable)
    if repay <= 0:
        return 0

    payload = {"grant": grant.source_key, "repay": repay}
    txn, created = await post_transaction(
        session,
        type="debt_repayment",
        idempotency_key=f"debt-repayment:{grant.source_key}",
        request_hash=canonical_request_hash(payload),
        account_id=grant.account_id,
        postings=[(DEBT, -repay), (CONSUMED, repay)],
        source_ref=grant.source_key,
        actor=actor,
        reason="grant allocated to prior uncovered consumption",
    )
    if not created:
        return 0
    remaining = repay
    for row in debt_rows:
        if remaining <= 0:
            break
        take = min(remaining, row.credits - row.repaid_credits)
        row.repaid_credits += take
        remaining -= take
        session.add(
            CreditConsumption(
                charge_transaction_id=txn.id,
                account_id=grant.account_id,
                grant_id=grant.id,
                credits=take,
            )
        )
    grant.remaining_credits -= repay
    if grant.remaining_credits == 0:
        grant.status = "exhausted"
    await session.flush()
    return repay


# ── Burn order + charging ────────────────────────────────────────────────────

async def _burnable_grants(
    session: AsyncSession, account_id: uuid.UUID, now: datetime
) -> list[CreditGrant]:
    result = await session.execute(
        select(CreditGrant)
        .where(
            CreditGrant.account_id == account_id,
            CreditGrant.status == "active",
            CreditGrant.remaining_credits > 0,
            CreditGrant.effective_at <= now,
        )
        .order_by(
            CreditGrant.burn_priority.asc(),
            # NULLS LAST for non-expiring lots, oldest first within a tier.
            CreditGrant.expires_at.is_(None).asc(),
            CreditGrant.expires_at.asc(),
            CreditGrant.effective_at.asc(),
            CreditGrant.created_at.asc(),
        )
    )
    return [g for g in result.scalars().all() if g.expires_at is None or _aware(g.expires_at) > now]


async def charge(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    idempotency_key: str,
    credits: int,
    agent_id: uuid.UUID | None = None,
    root_action_id: str | None = None,
    service: str | None = None,
    source_ref: str | None = None,
    commercial_pricing_version_id: uuid.UUID | None = None,
    provider_cost_version_id: uuid.UUID | None = None,
    reason: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
) -> CreditLedgerTransaction:
    """Post a completed charge in full — even into debt (5 → charge 10 → -5).
    Blocking happens at authorization time, never on a completed action."""
    if not isinstance(credits, int) or isinstance(credits, bool) or credits <= 0:
        raise BillingError("charge credits must be a positive int")
    now = now or _utcnow()

    await lock_billing_account(session, account_id)

    payload = {"account": str(account_id), "credits": credits, "kind": "charge"}
    request_hash = canonical_request_hash(payload)
    existing = await find_transaction(session, idempotency_key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict(idempotency_key)
        return existing

    covered = 0
    allocations: list[tuple[CreditGrant, int]] = []
    for grant in await _burnable_grants(session, account_id, now):
        if covered >= credits:
            break
        take = min(grant.remaining_credits, credits - covered)
        allocations.append((grant, take))
        covered += take
    uncovered = credits - covered

    postings = [(WALLET, -credits)]
    if covered:
        postings.append((CONSUMED, covered))
    if uncovered:
        postings.append((DEBT, uncovered))

    txn, created = await post_transaction(
        session,
        type="charge",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        account_id=account_id,
        postings=postings,
        agent_id=agent_id,
        root_action_id=root_action_id,
        service=service,
        source_ref=source_ref,
        commercial_pricing_version_id=commercial_pricing_version_id,
        provider_cost_version_id=provider_cost_version_id,
        reason=reason,
        actor=actor,
    )
    if created:
        for grant, take in allocations:
            grant.remaining_credits -= take
            if grant.remaining_credits == 0:
                grant.status = "exhausted"
            session.add(
                CreditConsumption(
                    charge_transaction_id=txn.id,
                    account_id=account_id,
                    grant_id=grant.id,
                    credits=take,
                )
            )
        if uncovered:
            session.add(
                CreditConsumption(
                    charge_transaction_id=txn.id,
                    account_id=account_id,
                    grant_id=None,
                    credits=uncovered,
                )
            )
        await session.flush()
        await rebuild_projection(session, account_id)
    return txn


async def expire_due_grants(
    session: AsyncSession, account_id: uuid.UUID, now: datetime | None = None
) -> list[CreditLedgerTransaction]:
    """Expire active lots past expires_at (exclusive boundary: a lot expiring
    at T is unusable at T)."""
    now = now or _utcnow()
    await lock_billing_account(session, account_id)
    result = await session.execute(
        select(CreditGrant).where(
            CreditGrant.account_id == account_id,
            CreditGrant.status.in_(["active", "scheduled"]),
            CreditGrant.expires_at.is_not(None),
            CreditGrant.expires_at <= now,
        )
    )
    txns: list[CreditLedgerTransaction] = []
    changed = False
    for grant in result.scalars().all():
        remaining = grant.remaining_credits
        posted = grant.grant_transaction_id is not None
        grant.status = "expired"
        grant.remaining_credits = 0
        changed = True
        if remaining > 0 and posted:
            payload = {"grant": grant.source_key, "expired": remaining}
            txn, _ = await post_transaction(
                session,
                type="expiration",
                idempotency_key=f"expire:{grant.source_key}",
                request_hash=canonical_request_hash(payload),
                account_id=account_id,
                postings=[(WALLET, -remaining), (EXPIRED, remaining)],
                source_ref=grant.source_key,
                actor="system",
            )
            txns.append(txn)
    if changed:
        await rebuild_projection(session, account_id)
    return txns


async def reverse_transaction(
    session: AsyncSession,
    *,
    transaction_id: uuid.UUID,
    reason: str,
    actor: str,
    idempotency_key: str | None = None,
) -> CreditLedgerTransaction:
    """Append-only reversal: negate the original postings and restore the
    economic source (grant remainders for charges; unconsumed lots for
    grants). History is never edited."""
    result = await session.execute(
        select(CreditLedgerTransaction).where(CreditLedgerTransaction.id == transaction_id)
    )
    original = result.scalar_one_or_none()
    if original is None:
        raise BillingError("transaction not found")
    if original.type == "reversal":
        raise BillingError("cannot reverse a reversal")

    await lock_billing_account(session, original.account_id)

    idempotency_key = idempotency_key or f"reversal:{original.idempotency_key}"
    payload = {"reversal_of": str(original.id)}
    request_hash = canonical_request_hash(payload)
    existing = await find_transaction(session, idempotency_key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict(idempotency_key)
        return existing

    postings_result = await session.execute(
        select(CreditLedgerPosting).where(CreditLedgerPosting.transaction_id == original.id)
    )
    original_postings = list(postings_result.scalars().all())

    if original.type == "charge":
        cons_result = await session.execute(
            select(CreditConsumption).where(
                CreditConsumption.charge_transaction_id == original.id
            )
        )
        for row in cons_result.scalars().all():
            if row.grant_id is not None:
                grant = await session.get(CreditGrant, row.grant_id)
                grant.remaining_credits += row.credits
                if grant.status == "exhausted":
                    grant.status = "active"
            else:
                # Uncovered portion: reversing the charge cancels that debt.
                row.repaid_credits = row.credits
    elif original.type == "grant":
        grant_result = await session.execute(
            select(CreditGrant).where(CreditGrant.grant_transaction_id == original.id)
        )
        grant = grant_result.scalar_one_or_none()
        if grant is None:
            raise BillingError("grant lot not found for grant transaction")
        if grant.remaining_credits != grant.original_credits:
            raise BillingError(
                "grant partially consumed — use the refund clawback flow (039/007)"
            )
        grant.remaining_credits = 0
        grant.status = "reversed"
    else:
        raise BillingError(f"reversal of type {original.type!r} not supported in 039/001")

    txn, _ = await post_transaction(
        session,
        type="reversal",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        account_id=original.account_id,
        postings=[(p.ledger_account, -p.credits) for p in original_postings],
        reversal_of_id=original.id,
        reason=reason,
        actor=actor,
    )
    await rebuild_projection(session, original.account_id)
    return txn


# ── Projection ───────────────────────────────────────────────────────────────

async def rebuild_projection(session: AsyncSession, account_id: uuid.UUID) -> AccountBalanceProjection:
    """Recompute the read model from the ledger + grants + holds. Stale writes
    are rejected by the last_seq check."""
    posted = (
        await session.execute(
            select(func.coalesce(func.sum(CreditLedgerPosting.credits), 0)).where(
                CreditLedgerPosting.account_id == account_id,
                CreditLedgerPosting.ledger_account == WALLET,
            )
        )
    ).scalar_one()
    debt = (
        await session.execute(
            select(func.coalesce(func.sum(CreditLedgerPosting.credits), 0)).where(
                CreditLedgerPosting.account_id == account_id,
                CreditLedgerPosting.ledger_account == DEBT,
            )
        )
    ).scalar_one()
    max_seq = (
        await session.execute(
            select(func.coalesce(func.max(CreditLedgerTransaction.seq), 0)).where(
                CreditLedgerTransaction.account_id == account_id
            )
        )
    ).scalar_one()
    open_exposure = (
        await session.execute(
            select(func.coalesce(func.sum(BillingHold.estimated_credits), 0)).where(
                BillingHold.account_id == account_id,
                # needs_reconciliation still counts: unresolved work must keep
                # bounding new authorizations until an operator settles it.
                BillingHold.status.in_(["open", "needs_reconciliation"]),
            )
        )
    ).scalar_one()

    by_category = {"bonus": 0, "gift": 0, "free": 0, "paid": 0, "topup": 0}
    next_expiry: datetime | None = None
    grants = await session.execute(
        select(CreditGrant).where(
            CreditGrant.account_id == account_id,
            CreditGrant.status == "active",
            CreditGrant.remaining_credits > 0,
        )
    )
    for grant in grants.scalars().all():
        by_category[grant.visible_category] += grant.remaining_credits
        expires = _aware(grant.expires_at)
        if expires is not None and (next_expiry is None or expires < next_expiry):
            next_expiry = expires

    projection = await session.get(AccountBalanceProjection, account_id)
    if projection is None:
        projection = AccountBalanceProjection(account_id=account_id)
        session.add(projection)
    elif projection.last_seq > max_seq:
        return projection  # stale writer — a newer state is already recorded

    projection.posted_balance_credits = posted
    projection.bonus_credits = by_category["bonus"]
    projection.gift_credits = by_category["gift"]
    projection.free_credits = by_category["free"]
    projection.paid_credits = by_category["paid"]
    projection.topup_credits = by_category["topup"]
    projection.debt_credits = debt
    projection.open_exposure_credits = open_exposure
    projection.next_expiry_at = next_expiry
    projection.last_seq = max_seq
    await session.flush()
    return projection


async def posted_balance(session: AsyncSession, account_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.coalesce(func.sum(CreditLedgerPosting.credits), 0)).where(
                CreditLedgerPosting.account_id == account_id,
                CreditLedgerPosting.ledger_account == WALLET,
            )
        )
    ).scalar_one()


# ── Authorize / settle / release ─────────────────────────────────────────────

def _day_period(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _month_period(now: datetime) -> tuple[datetime, datetime]:
    now = now.astimezone(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


async def _limit_period(
    session: AsyncSession, agent_id: uuid.UUID, kind: str, now: datetime
) -> AgentLimitPeriod:
    start, end = _day_period(now) if kind == "daily" else _month_period(now)
    result = await session.execute(
        select(AgentLimitPeriod).where(
            AgentLimitPeriod.agent_id == agent_id,
            AgentLimitPeriod.period_kind == kind,
            AgentLimitPeriod.period_start == start,
        )
    )
    period = result.scalar_one_or_none()
    if period is None:
        period = AgentLimitPeriod(
            agent_id=agent_id, period_kind=kind, period_start=start, period_end=end
        )
        session.add(period)
        await session.flush()
    return period


async def authorize(
    session: AsyncSession,
    *,
    operation_id: str,
    account_id: uuid.UUID,
    estimated_credits: int,
    agent_id: uuid.UUID | None = None,
    root_action_id: str | None = None,
    service: str | None = None,
    sku: str | None = None,
    commercial_pricing_version_id: uuid.UUID | None = None,
    provider_cost_version_id: uuid.UUID | None = None,
    count_toward_limits: bool = True,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_HOLD_TTL,
) -> BillingHold:
    """Open a hold. Raises InsufficientBalance / LimitExceeded when blocked.

    Rules: paid actions are blocked at posted balance <= 0; a hold larger than
    availability is the account's single bounded uncovered overrun (default cap
    1,000); additional concurrent work needs positive availability.
    """
    if not isinstance(estimated_credits, int) or isinstance(estimated_credits, bool) or estimated_credits < 0:
        raise BillingError("estimated_credits must be a nonnegative int")
    now = now or _utcnow()

    acct = await lock_billing_account(session, account_id)

    payload = {
        "op": operation_id,
        "account": str(account_id),
        "agent": str(agent_id) if agent_id else None,
        "estimated": estimated_credits,
        "service": service,
        "sku": sku,
    }
    request_hash = canonical_request_hash(payload)
    existing = await session.execute(
        select(BillingHold).where(BillingHold.operation_id == operation_id)
    )
    hold = existing.scalar_one_or_none()
    if hold is not None:
        if hold.request_hash != request_hash:
            raise IdempotencyConflict(operation_id)
        return hold

    # Bring the account current before deciding.
    await expire_due_grants(session, account_id, now)
    await activate_scheduled_grants(session, account_id, now)

    balance = await posted_balance(session, account_id)
    if balance <= 0:
        raise InsufficientBalance(f"posted balance {balance} <= 0")

    open_holds = (
        await session.execute(
            select(BillingHold).where(
                BillingHold.account_id == account_id,
                BillingHold.status.in_(["open", "needs_reconciliation"]),
            )
        )
    ).scalars().all()
    open_exposure = sum(h.estimated_credits for h in open_holds)
    available = balance - open_exposure

    overrun = max(estimated_credits - max(available, 0), 0)
    if overrun > 0:
        if available <= 0:
            raise LimitExceeded(
                "exposure_limit", "concurrent work requires positive availability"
            )
        if any(h.overrun_credits > 0 for h in open_holds):
            raise LimitExceeded("exposure_limit", "an uncovered overrun is already in flight")
        if overrun > acct.overrun_cap_credits:
            raise LimitExceeded(
                "exposure_limit",
                f"overrun {overrun} exceeds cap {acct.overrun_cap_credits}",
            )

    daily_period = monthly_period = None
    if agent_id is not None and count_toward_limits:
        limits = await session.get(AgentCreditLimit, agent_id)
        if limits is not None:
            if limits.daily_limit_credits is not None:
                daily_period = await _limit_period(session, agent_id, "daily", now)
                if (
                    daily_period.settled_credits
                    + daily_period.open_exposure_credits
                    + estimated_credits
                    > limits.daily_limit_credits
                ):
                    raise LimitExceeded("luna_daily_limit")
            if limits.monthly_limit_credits is not None:
                monthly_period = await _limit_period(session, agent_id, "monthly", now)
                if (
                    monthly_period.settled_credits
                    + monthly_period.open_exposure_credits
                    + estimated_credits
                    > limits.monthly_limit_credits
                ):
                    raise LimitExceeded("luna_monthly_limit")

    hold = BillingHold(
        operation_id=operation_id,
        request_hash=request_hash,
        account_id=account_id,
        agent_id=agent_id,
        root_action_id=root_action_id,
        service=service,
        sku=sku,
        commercial_pricing_version_id=commercial_pricing_version_id,
        provider_cost_version_id=provider_cost_version_id,
        estimated_credits=estimated_credits,
        overrun_credits=overrun,
        authorized_at=now,
        expires_at=now + ttl,
    )
    session.add(hold)
    if daily_period is not None:
        daily_period.open_exposure_credits += estimated_credits
    if monthly_period is not None:
        monthly_period.open_exposure_credits += estimated_credits
    await session.flush()
    await rebuild_projection(session, account_id)
    return hold


async def _get_hold(session: AsyncSession, operation_id: str) -> BillingHold:
    result = await session.execute(
        select(BillingHold).where(BillingHold.operation_id == operation_id)
    )
    hold = result.scalar_one_or_none()
    if hold is None:
        raise BillingError(f"no hold for operation {operation_id}")
    return hold


async def _drain_limit_exposure(
    session: AsyncSession, hold: BillingHold, settled_credits: int, now: datetime
) -> None:
    if hold.agent_id is None:
        return
    limits = await session.get(AgentCreditLimit, hold.agent_id)
    if limits is None:
        return
    for kind, limit in (("daily", limits.daily_limit_credits), ("monthly", limits.monthly_limit_credits)):
        if limit is None:
            continue
        # Exposure was recorded in the period of authorization time.
        period = await _limit_period(session, hold.agent_id, kind, _aware(hold.authorized_at))
        period.open_exposure_credits = max(
            period.open_exposure_credits - hold.estimated_credits, 0
        )
        if settled_credits:
            settle_period = await _limit_period(session, hold.agent_id, kind, now)
            settle_period.settled_credits += settled_credits
    await session.flush()


async def settle(
    session: AsyncSession,
    *,
    operation_id: str,
    final_credits: int,
    reason: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
) -> CreditLedgerTransaction:
    """Settle an open hold at the final rated amount — posted in full even
    into debt. Idempotent per operation."""
    now = now or _utcnow()
    hold = await _get_hold(session, operation_id)
    await lock_billing_account(session, hold.account_id)

    if hold.status == "settled":
        existing = await find_transaction(session, f"settle:{operation_id}")
        if existing is not None:
            return existing
        raise BillingError(f"hold {operation_id} settled but its transaction is missing")
    if hold.status not in ("open", "needs_reconciliation"):
        raise BillingError(f"hold {operation_id} is {hold.status}, cannot settle")

    txn = await charge(
        session,
        account_id=hold.account_id,
        idempotency_key=f"settle:{operation_id}",
        credits=final_credits,
        agent_id=hold.agent_id,
        root_action_id=hold.root_action_id,
        service=hold.service,
        source_ref=operation_id,
        commercial_pricing_version_id=hold.commercial_pricing_version_id,
        provider_cost_version_id=hold.provider_cost_version_id,
        reason=reason,
        actor=actor,
        now=now,
    )
    hold.status = "settled"
    hold.settled_at = now
    hold.settle_transaction_id = txn.id
    await _drain_limit_exposure(session, hold, final_credits, now)
    await session.flush()
    await rebuild_projection(session, hold.account_id)
    return txn


async def release(
    session: AsyncSession, *, operation_id: str, now: datetime | None = None
) -> BillingHold:
    """Release an open hold with no charge (blocked upstream, absorbed, …)."""
    now = now or _utcnow()
    hold = await _get_hold(session, operation_id)
    await lock_billing_account(session, hold.account_id)
    if hold.status == "released":
        return hold
    if hold.status != "open":
        raise BillingError(f"hold {operation_id} is {hold.status}, cannot release")
    hold.status = "released"
    hold.released_at = now
    await _drain_limit_exposure(session, hold, 0, now)
    await session.flush()
    await rebuild_projection(session, hold.account_id)
    return hold


async def mark_stale_holds(
    session: AsyncSession, *, now: datetime | None = None
) -> list[BillingHold]:
    """Holds past their TTL move to needs_reconciliation — never silently
    released and never silently settled."""
    now = now or _utcnow()
    result = await session.execute(
        select(BillingHold).where(
            BillingHold.status == "open", BillingHold.expires_at <= now
        )
    )
    stale = list(result.scalars().all())
    for hold in stale:
        hold.status = "needs_reconciliation"
    if stale:
        await session.flush()
        for account_id in {h.account_id for h in stale}:
            await rebuild_projection(session, account_id)
    return stale
