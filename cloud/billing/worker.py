"""Durable billing worker (039/001).

Financial jobs must survive crashes and deploys — the in-process lifespan
loops (relay forwarder / reconciler) are not sufficient. Jobs live in
`billing_outbox`: claimed with FOR UPDATE SKIP LOCKED on Postgres, leased
with heartbeats, retried with bounded exponential backoff, and moved to a
visible `dead` state when poisoned. Handlers must be idempotent — a job can
run more than once (lease expiry), but its effects may not.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing.models import BillingJob

log = logging.getLogger("billing.worker")

DEFAULT_LEASE = timedelta(minutes=5)
BASE_BACKOFF = timedelta(seconds=30)
MAX_BACKOFF = timedelta(hours=4)

# job_type -> async handler(session, job) -> result dict | None
Handler = Callable[[AsyncSession, BillingJob], Awaitable[dict | None]]
_handlers: dict[str, Handler] = {}


def register_handler(job_type: str, handler: Handler) -> None:
    _handlers[job_type] = handler


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def backoff_for_attempt(attempt: int) -> timedelta:
    """Bounded exponential backoff: 30s, 1m, 2m, ... capped at 4h."""
    # Clamp the exponent — 2**30 * 30s already exceeds MAX_BACKOFF by orders
    # of magnitude and huge attempt counts overflow timedelta arithmetic.
    delay = BASE_BACKOFF * (2 ** min(max(attempt - 1, 0), 30))
    return min(delay, MAX_BACKOFF)


async def enqueue(
    session: AsyncSession,
    *,
    job_type: str,
    payload: dict,
    dedupe_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 8,
) -> BillingJob:
    """Insert a durable job in the caller's DB transaction, so the job exists
    iff the financial state that scheduled it committed."""
    if dedupe_key is not None:
        existing = await session.execute(
            select(BillingJob).where(BillingJob.dedupe_key == dedupe_key)
        )
        job = existing.scalar_one_or_none()
        if job is not None:
            return job
    job = BillingJob(
        job_type=job_type,
        payload=payload,
        dedupe_key=dedupe_key,
        next_attempt_at=run_at or _utcnow(),
        max_attempts=max_attempts,
    )
    session.add(job)
    await session.flush()
    return job


async def claim_jobs(
    session: AsyncSession,
    *,
    worker_id: str,
    limit: int = 10,
    lease: timedelta = DEFAULT_LEASE,
    now: datetime | None = None,
) -> list[BillingJob]:
    """Claim due jobs: pending-and-due, or running with an expired lease
    (crashed worker). SKIP LOCKED on Postgres so concurrent workers never
    double-claim; SQLite tests run single-connection."""
    now = now or _utcnow()
    stmt = (
        select(BillingJob)
        .where(
            (
                (BillingJob.status == "pending") & (BillingJob.next_attempt_at <= now)
            )
            | (
                (BillingJob.status == "running") & (BillingJob.lease_expires_at <= now)
            )
        )
        .order_by(BillingJob.next_attempt_at.asc())
        .limit(limit)
    )
    if session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = "running"
        job.leased_by = worker_id
        job.lease_expires_at = now + lease
        job.attempts += 1
    await session.flush()
    return jobs


async def heartbeat(
    session: AsyncSession, job_id: uuid.UUID, *, worker_id: str,
    lease: timedelta = DEFAULT_LEASE, now: datetime | None = None,
) -> bool:
    """Extend the lease. Returns False if the job is no longer ours."""
    now = now or _utcnow()
    job = await session.get(BillingJob, job_id)
    if job is None or job.status != "running" or job.leased_by != worker_id:
        return False
    job.lease_expires_at = now + lease
    await session.flush()
    return True


async def complete_job(session: AsyncSession, job: BillingJob, result: dict | None = None) -> None:
    job.status = "succeeded"
    job.result = result
    job.lease_expires_at = None
    await session.flush()


async def fail_job(
    session: AsyncSession, job: BillingJob, error: str, *, now: datetime | None = None
) -> None:
    """Retry with backoff, or dead-letter once attempts are exhausted."""
    now = now or _utcnow()
    job.last_error = error[:4000]
    job.lease_expires_at = None
    if job.attempts >= job.max_attempts:
        job.status = "dead"
    else:
        job.status = "pending"
        job.next_attempt_at = now + backoff_for_attempt(job.attempts)
    await session.flush()


async def run_claimed_job(session: AsyncSession, job: BillingJob) -> bool:
    """Execute one claimed job through its registered handler."""
    handler = _handlers.get(job.job_type)
    if handler is None:
        await fail_job(session, job, f"no handler registered for {job.job_type!r}")
        return False
    job_id = job.id  # captured before the handler — rollback expires the instance
    try:
        result = await handler(session, job)
    except Exception as exc:  # noqa: BLE001 — a poisoned job must never kill the worker
        await session.rollback()
        job_row = await session.get(BillingJob, job_id)
        if job_row is None:  # claim was never committed (should not happen via run_once)
            log.error("job %s vanished after handler rollback", job_id)
            return False
        await fail_job(session, job_row, f"{exc}\n{traceback.format_exc()}")
        return False
    await complete_job(session, job, result)
    return True


async def run_once(session: AsyncSession, *, worker_id: str, limit: int = 10) -> int:
    """One worker tick: claim due jobs and run them. Returns completed count."""
    jobs = await claim_jobs(session, worker_id=worker_id, limit=limit)
    await session.commit()
    done = 0
    for job in jobs:
        ok = await run_claimed_job(session, job)
        await session.commit()
        done += 1 if ok else 0
    return done


async def worker_loop(session_factory, *, worker_id: str, interval_seconds: float = 5.0):
    """Long-running loop for the deployment entrypoint (advisory-lock guarded
    by the caller, like the existing background loops)."""
    while True:
        try:
            async with session_factory() as session:
                await run_once(session, worker_id=worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("billing worker tick failed")
        await asyncio.sleep(interval_seconds)
