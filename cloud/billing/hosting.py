"""Hosting lifecycle (039/005): 999-credit periods, durable provisioning,
monthly-anchor renewal, payment_due, teardown.

Money moves only in enforce mode (`CLOUD_BILLING_MODE=enforce`, the same env
contract as gateway enforcement). In off/observe/shadow the lifecycle rows
(periods, allocations) are still written — with no ledger movement — so the
data is real before enforcement is turned on.

Durability: provisioning, suspend, and teardown are `billing_outbox` jobs.
The API call commits the intent (period row + hold + job) and returns; the
worker does the network work. A crash between hold and settle leaves the hold
for the stale-hold reaper (`needs_reconciliation`) — never a silent release
after external work may have started.
"""

from __future__ import annotations

import calendar
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import ledger, rating
from cloud.billing.models import AgentHostingPeriod, BillingJob, ResourceAllocation
from cloud.billing.worker import enqueue, register_handler
from cloud.db.models import Agent

log = logging.getLogger(__name__)

PROVISION_JOB = "hosting_provision"
SUSPEND_JOB = "hosting_suspend"
TEARDOWN_JOB = "agent_teardown"

# Provisioning can legitimately take minutes (image pull, volume create,
# health wait) — the hold must outlive it, and the reaper picks up the rest.
PROVISION_HOLD_TTL = timedelta(minutes=30)


class HostingError(ledger.BillingError):
    """Hosting cannot be paid for — carries a block-contract code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def billing_mode() -> str:
    """Same env contract as gateway enforcement; duplicated here so the
    billing layer does not import the gateway layer."""
    mode = os.environ.get("CLOUD_BILLING_MODE", "off").strip().lower()
    return mode if mode in ("off", "observe", "shadow", "enforce") else "off"


def hosting_billing_active() -> bool:
    """Ledger movements for hosting happen only in enforce mode (global —
    per-account decisions use hosting_enforced)."""
    return billing_mode() == "enforce"


async def effective_mode_for(session: AsyncSession, account_id: uuid.UUID) -> str:
    """The account's effective billing mode (039/010): max of the global mode
    and the account's enforcement override."""
    from cloud.billing import modes

    return await modes.effective_mode(session, account_id, billing_mode())


async def hosting_enforced(session: AsyncSession, account_id: uuid.UUID) -> bool:
    return await effective_mode_for(session, account_id) == "enforce"


def hosting_price(config: dict) -> int:
    """One source of truth: the hosting_month SKU constant (002 validation
    guarantees it equals config.hosting.price_credits)."""
    for sku in config.get("skus") or []:
        if sku.get("key") == "hosting_month":
            return int(sku["constants"]["price_credits"])
    return int((config.get("hosting") or {})["price_credits"])


def add_month_clamped(anchor_day: int, after: datetime) -> datetime:
    """The next monthly-anchor boundary after `after`, clamped for short
    months but returning to the anchor day (Jan 31 → Feb 28 → Mar 31)."""
    year, month = after.year, after.month
    month += 1
    if month > 12:
        year, month = year + 1, 1
    day = min(anchor_day, calendar.monthrange(year, month)[1])
    return after.replace(year=year, month=month, day=day)


async def _anchor_day(session: AsyncSession, agent_id: uuid.UUID) -> int | None:
    """The agent's billing anchor: the day-of-month of its first period."""
    first = (
        await session.execute(
            select(AgentHostingPeriod.starts_at)
            .where(AgentHostingPeriod.agent_id == agent_id)
            .order_by(AgentHostingPeriod.starts_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return first.day if first else None


# ── Creation ─────────────────────────────────────────────────────────────────

async def start_hosting(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    account_id: uuid.UUID,
    now: datetime | None = None,
) -> AgentHostingPeriod:
    """Open the first hosting period for a new agent and enqueue durable
    provisioning. In enforce mode this authorizes exactly the hosting price
    (settled by the provisioning handler once resources are confirmed);
    insufficient balance raises HostingError before anything is created.
    Idempotent per (agent, starts_at) intent via the job dedupe key.
    """
    now = now or _utcnow()
    await ledger.lock_billing_account(session, account_id)

    existing = (
        await session.execute(
            select(AgentHostingPeriod).where(
                AgentHostingPeriod.agent_id == agent_id,
                AgentHostingPeriod.state.in_(["pending", "active", "payment_due"]),
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing

    version_id, config = await rating.resolve_commercial_version(session, account_id, now)
    price = hosting_price(config)

    enforce = await hosting_enforced(session, account_id)
    if enforce and await ledger.posted_balance(session, account_id) < price:
        # Explicit check: the ledger's bounded-overrun would let a 999 hold
        # through once on an empty wallet, and hosting must never enter debt.
        raise HostingError(
            "credits_exhausted",
            f"Hosting needs {price} credits; the account balance does not cover it.",
        )

    period = AgentHostingPeriod(
        agent_id=agent_id,
        account_id=account_id,
        starts_at=now,
        ends_at=add_month_clamped(now.day, now),
        price_credits=price,
        commercial_pricing_version_id=version_id,
        state="pending",
    )
    session.add(period)
    await session.flush()

    if enforce:
        await ledger.authorize(
            session,
            operation_id=f"hosting:{period.id}",
            account_id=account_id,
            estimated_credits=price,
            agent_id=agent_id,
            service="hosting",
            sku="hosting_month",
            commercial_pricing_version_id=version_id,
            count_toward_limits=False,  # hosting never consumes per-Luna budget
            now=now,
            ttl=PROVISION_HOLD_TTL,
        )

    await enqueue(
        session,
        job_type=PROVISION_JOB,
        payload={
            "agent_id": str(agent_id),
            "account_id": str(account_id),
            "period_id": str(period.id),
        },
        dedupe_key=f"hostprov:{period.id}",
    )
    return period


async def retry_provisioning(session: AsyncSession, agent_id: uuid.UUID) -> bool:
    """User-initiated retry: requeue the pending period's provisioning job
    (a dead-lettered or backed-off job runs again immediately). Returns False
    when the agent has no pending hosting period — the caller falls back to
    the legacy direct provisioning path."""
    period = (
        await session.execute(
            select(AgentHostingPeriod)
            .where(
                AgentHostingPeriod.agent_id == agent_id,
                AgentHostingPeriod.state == "pending",
            )
            .order_by(AgentHostingPeriod.starts_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if period is None:
        return False
    job = (
        await session.execute(
            select(BillingJob).where(BillingJob.dedupe_key == f"hostprov:{period.id}")
        )
    ).scalar_one_or_none()
    now = _utcnow()
    if job is None:
        await enqueue(
            session,
            job_type=PROVISION_JOB,
            payload={
                "agent_id": str(agent_id),
                "account_id": str(period.account_id),
                "period_id": str(period.id),
            },
            dedupe_key=f"hostprov:{period.id}",
        )
    elif job.status in ("dead", "pending"):
        job.status = "pending"
        job.attempts = 0
        job.next_attempt_at = now
        job.last_error = None
    return True


# ── Guard + recovery ─────────────────────────────────────────────────────────

async def hosting_blocked(session: AsyncSession, agent_id: uuid.UUID) -> bool:
    """One hosting-state guard for every start/wake path: True while any
    payment_due period exists for the agent. Enforced only when the agent's
    account is effectively in enforce mode (global or override)."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return False
    if not await hosting_enforced(session, agent.account_id):
        return False
    row = (
        await session.execute(
            select(AgentHostingPeriod.id)
            .where(
                AgentHostingPeriod.agent_id == agent_id,
                AgentHostingPeriod.state == "payment_due",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def try_recover_payment_due(
    session: AsyncSession, agent: Agent, *, now: datetime | None = None
) -> bool:
    """Restart path: if the balance now covers a fresh month, charge it,
    close the payment_due period, and open a newly paid period. Returns
    False (leaving everything blocked) when the balance still can't cover."""
    now = now or _utcnow()
    account_id = agent.account_id
    await ledger.lock_billing_account(session, account_id)
    due = (
        await session.execute(
            select(AgentHostingPeriod).where(
                AgentHostingPeriod.agent_id == agent.id,
                AgentHostingPeriod.state == "payment_due",
            )
        )
    ).scalars().all()
    if not due:
        return True

    version_id, config = await rating.resolve_commercial_version(session, account_id, now)
    price = hosting_price(config)
    if await ledger.posted_balance(session, account_id) < price:
        return False

    anchor = await _anchor_day(session, agent.id) or now.day
    period = AgentHostingPeriod(
        agent_id=agent.id,
        account_id=account_id,
        starts_at=now,
        ends_at=add_month_clamped(anchor, now),
        price_credits=price,
        commercial_pricing_version_id=version_id,
        state="active",
    )
    session.add(period)
    await session.flush()
    txn = await ledger.charge(
        session,
        account_id=account_id,
        idempotency_key=f"hosting_recover:{period.id}",
        credits=price,
        agent_id=agent.id,
        service="hosting",
        source_ref=str(period.id),
        commercial_pricing_version_id=version_id,
        reason="hosting recovery after payment_due",
        actor="system",
        now=now,
    )
    period.charge_transaction_id = txn.id
    for p in due:
        p.state = "ended"
    return True


async def end_hosting_for_agent(
    session: AsyncSession, agent_id: uuid.UUID, *, now: datetime | None = None
) -> None:
    """Agent deletion: close open periods. The already-paid charge stands
    (early deletion forfeits the remainder of the month); pending unsettled
    periods are left for the provisioning handler / reaper to resolve."""
    now = now or _utcnow()
    periods = (
        await session.execute(
            select(AgentHostingPeriod).where(
                AgentHostingPeriod.agent_id == agent_id,
                AgentHostingPeriod.state.in_(["active", "payment_due"]),
            )
        )
    ).scalars().all()
    for p in periods:
        p.state = "ended"


# ── Renewal sweep ────────────────────────────────────────────────────────────

async def renew_due_periods(
    session: AsyncSession, *, now: datetime | None = None
) -> list[AgentHostingPeriod]:
    """Renew every active period past its end. Exact-price charge on the
    monthly anchor (clamped); a balance that can't cover marks the period
    payment_due and enqueues a durable machine suspend. Idempotent: the
    charge key and the suspend dedupe key are both derived from the expiring
    period id."""
    now = now or _utcnow()
    due = (
        await session.execute(
            select(AgentHostingPeriod)
            .where(
                AgentHostingPeriod.state == "active",
                AgentHostingPeriod.ends_at <= now,
            )
            .order_by(AgentHostingPeriod.ends_at.asc())
        )
    ).scalars().all()

    renewed: list[AgentHostingPeriod] = []
    for old in due:
        agent = await session.get(Agent, old.agent_id)
        if agent is None or agent.deleted_at is not None:
            old.state = "ended"
            continue

        await ledger.lock_billing_account(session, old.account_id)
        version_id, config = await rating.resolve_commercial_version(
            session, old.account_id, now
        )
        price = hosting_price(config)
        anchor = await _anchor_day(session, old.agent_id) or old.starts_at.day
        starts = old.ends_at
        ends = add_month_clamped(anchor, starts)

        enforce = await hosting_enforced(session, old.account_id)
        if enforce:
            balance = await ledger.posted_balance(session, old.account_id)
            if balance < price:
                old.state = "payment_due"
                await enqueue(
                    session,
                    job_type=SUSPEND_JOB,
                    payload={"agent_id": str(old.agent_id)},
                    dedupe_key=f"hostsusp:{old.id}",
                )
                log.warning(
                    "hosting renewal unpayable for agent %s (balance %s < %s) — payment_due",
                    old.agent_id, balance, price,
                )
                continue

        new = AgentHostingPeriod(
            agent_id=old.agent_id,
            account_id=old.account_id,
            starts_at=starts,
            ends_at=ends,
            price_credits=price,
            commercial_pricing_version_id=version_id,
            state="active",
        )
        session.add(new)
        await session.flush()
        if enforce:
            txn = await ledger.charge(
                session,
                account_id=old.account_id,
                idempotency_key=f"hosting_renew:{old.id}",
                credits=price,
                agent_id=old.agent_id,
                service="hosting",
                source_ref=str(new.id),
                commercial_pricing_version_id=version_id,
                reason="hosting monthly renewal",
                actor="system",
                now=now,
            )
            new.charge_transaction_id = txn.id
        old.state = "ended"
        renewed.append(new)
    return renewed


# ── Durable job handlers ─────────────────────────────────────────────────────

def _runtime():
    from cloud.provisioning.workflow import _get_runtime

    return _get_runtime()


async def _handle_hosting_provision(session: AsyncSession, job: BillingJob) -> dict | None:
    """Provision the Luna, then settle the hosting hold and activate the
    period. Re-runnable from the committed job row alone: an already-active
    period returns immediately; provisioning itself is idempotent (reuses an
    existing machine). Network work runs outside any open DB transaction."""
    period_id = uuid.UUID(job.payload["period_id"])
    account_id = job.payload["account_id"]
    agent_id = job.payload["agent_id"]

    period = await session.get(AgentHostingPeriod, period_id)
    if period is None:
        return {"skipped": "period gone"}
    if period.state in ("active", "ended", "stopped"):
        return {"skipped": f"period already {period.state}"}

    agent = await session.get(Agent, uuid.UUID(agent_id))
    if agent is None or agent.deleted_at is not None:
        if await hosting_enforced(session, period.account_id):
            try:
                await ledger.release(session, operation_id=f"hosting:{period_id}")
            except ledger.BillingError:
                pass  # never held (mode changed) or already terminal
        period.state = "stopped"
        return {"skipped": "agent deleted before provisioning"}

    # Close our transaction before the network call — Fly work must never run
    # inside an open DB session (and can take minutes).
    await session.commit()

    from cloud.provisioning.workflow import provision_luna_for_account

    provisioned = await provision_luna_for_account(account_id, agent_id=agent_id)
    if provisioned is None or provisioned.status != "running":
        raise RuntimeError(f"provisioning did not reach running for agent {agent_id}")

    period = await session.get(AgentHostingPeriod, period_id)
    agent = await session.get(Agent, uuid.UUID(agent_id))
    now = _utcnow()

    machine_alloc = ResourceAllocation(
        agent_id=agent.id,
        account_id=period.account_id,
        resource_kind="machine",
        provider=agent.runtime_kind or "unknown",
        sku=None,  # included in hosting_month — never separately charged
        provider_resource_id=agent.runtime_ref,
        dimensions={"included_in": "hosting_month"},
        opened_at=now,
        reconcile_state="confirmed",
    )
    session.add(machine_alloc)
    if agent.volume_id:
        session.add(ResourceAllocation(
            agent_id=agent.id,
            account_id=period.account_id,
            resource_kind="volume",
            provider=agent.runtime_kind or "unknown",
            sku=None,
            provider_resource_id=agent.volume_id,
            dimensions={
                "included_in": "hosting_month",
                "size_gb": agent.volume_size_gb,
            },
            opened_at=now,
            reconcile_state="confirmed",
        ))
    await session.flush()
    period.resource_allocation_id = machine_alloc.id

    if await hosting_enforced(session, period.account_id):
        try:
            txn = await ledger.settle(
                session,
                operation_id=f"hosting:{period_id}",
                final_credits=period.price_credits,
                reason="hosting month settled on confirmed provisioning",
                actor="system",
                now=now,
            )
            period.charge_transaction_id = txn.id
        except ledger.BillingError as exc:
            # No settleable hold: it never existed (mode flipped to enforce
            # after creation) or is terminal (released/expired). The customer
            # has the machine — activate the period and let ops reconcile;
            # retrying the job would never make the settle succeed.
            log.error(
                "hosting settle failed for period %s (agent %s): %s — "
                "activating period, leaving hold for reconciliation",
                period_id, agent_id, exc,
            )
    period.state = "active"
    return {"period": str(period_id), "state": "active"}


async def _handle_hosting_suspend(session: AsyncSession, job: BillingJob) -> dict | None:
    """Stop the machine of a payment_due Luna. Idempotent — stopping a
    stopped machine is a no-op at the runtime."""
    agent = await session.get(Agent, uuid.UUID(job.payload["agent_id"]))
    if agent is None or not agent.runtime_ref:
        return {"skipped": "no runtime"}
    handle_args = (
        agent.runtime_kind or "fly-machine",
        agent.runtime_ref,
        agent.internal_url or "",
    )
    await session.commit()  # network next — leave no transaction open

    from cloud.runtime.base import RuntimeHandle

    await _runtime().stop(RuntimeHandle(*handle_args))
    agent = await session.get(Agent, uuid.UUID(job.payload["agent_id"]))
    agent.status = "stopped"
    return {"stopped": str(agent.id)}


async def _handle_agent_teardown(session: AsyncSession, job: BillingJob) -> dict | None:
    """Destroy the tombstoned agent's runtime resources (machine + volume)
    and close its allocation records. Financial rows are never deleted."""
    agent = await session.get(Agent, uuid.UUID(job.payload["agent_id"]))
    if agent is None:
        return {"skipped": "agent gone"}
    runtime_args = None
    if agent.runtime_ref:
        runtime_args = (
            agent.runtime_kind or "fly-machine",
            agent.runtime_ref,
            agent.internal_url or "",
            {"volume_id": agent.volume_id, "agent_slug": agent.slug},
        )
    await session.commit()  # network next

    if runtime_args:
        from cloud.runtime.base import RuntimeHandle

        kind, ref, url, extra = runtime_args
        await _runtime().destroy(RuntimeHandle(kind, ref, url, extra=extra))

    now = _utcnow()
    agent = await session.get(Agent, uuid.UUID(job.payload["agent_id"]))
    agent.runtime_ref = None
    agent.internal_url = None
    allocations = (
        await session.execute(
            select(ResourceAllocation).where(
                ResourceAllocation.agent_id == agent.id,
                ResourceAllocation.closed_at.is_(None),
            )
        )
    ).scalars().all()
    for alloc in allocations:
        alloc.closed_at = now
        alloc.reconcile_state = "closed"
    return {"torn_down": str(agent.id)}


register_handler(PROVISION_JOB, _handle_hosting_provision)
register_handler(SUSPEND_JOB, _handle_hosting_suspend)
register_handler(TEARDOWN_JOB, _handle_agent_teardown)
