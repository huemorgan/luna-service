"""Billing maintenance sweeps (039/005): grant expiry, scheduled-lot
activation, hosting renewals.

One loop, three idempotent sweeps, each in its own transaction. Runs beside
the outbox worker and the stale-hold reaper under the billing advisory lock
(wired in cloud/main.py) — 004's lesson: a loop that isn't started in the
lifespan doesn't exist.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import hosting, ledger
from cloud.billing.models import CreditGrant

log = logging.getLogger(__name__)

MAINTENANCE_INTERVAL_SECONDS = 60.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def expire_due_grants_sweep(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Expire every account's overdue lots. Append-only, rerun-safe."""
    now = now or _utcnow()
    account_ids = (
        await session.execute(
            select(CreditGrant.account_id)
            .where(
                CreditGrant.status.in_(["active", "scheduled"]),
                CreditGrant.expires_at.is_not(None),
                CreditGrant.expires_at <= now,
            )
            .distinct()
        )
    ).scalars().all()
    expired = 0
    for account_id in account_ids:
        expired += len(await ledger.expire_due_grants(session, account_id, now=now))
    return expired


async def activate_scheduled_grants_sweep(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Activate due scheduled lots (yearly buckets). Rerun-safe; lots that
    were delayed past several boundaries all activate on the next sweep."""
    now = now or _utcnow()
    account_ids = (
        await session.execute(
            select(CreditGrant.account_id)
            .where(
                CreditGrant.status == "scheduled",
                CreditGrant.effective_at <= now,
            )
            .distinct()
        )
    ).scalars().all()
    activated = 0
    for account_id in account_ids:
        activated += len(await ledger.activate_scheduled_grants(session, account_id, now=now))
    return activated


async def maintenance_once(session: AsyncSession, *, now: datetime | None = None) -> dict:
    now = now or _utcnow()
    expired = await expire_due_grants_sweep(session, now=now)
    activated = await activate_scheduled_grants_sweep(session, now=now)
    renewed = len(await hosting.renew_due_periods(session, now=now))
    return {"expired": expired, "activated": activated, "renewed": renewed}


async def maintenance_loop(
    session_factory, *, interval_seconds: float = MAINTENANCE_INTERVAL_SECONDS
) -> None:
    while True:
        try:
            async with session_factory() as session:
                result = await maintenance_once(session)
                await session.commit()
                if any(result.values()):
                    log.info("billing maintenance: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("billing maintenance sweep failed")
        await asyncio.sleep(interval_seconds)
