"""Single-runner guard for background loops (plan 037-SPEED101).

With `uvicorn --workers N` every worker executes the lifespan, so unguarded
background loops (relay forwarder, reconciler) would run N times. Each loop
runs under a Postgres advisory lock: one worker holds the lock and runs; the
others retry periodically and take over if the holder dies.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text

log = logging.getLogger(__name__)

RETRY_INTERVAL = 60

# Stable lock ids (arbitrary but unique per loop).
LOCK_RELAY_FORWARDER = 0x1004A_01
LOCK_RECONCILER = 0x1004A_02
LOCK_BILLING_WORKER = 0x1004A_03


async def run_exclusive(lock_key: int, name: str, loop_fn: Callable[[], Awaitable[None]]) -> None:
    from cloud.db.session import _get_engine

    engine = _get_engine()
    while True:
        try:
            # Dedicated connection held for the whole run — advisory locks are
            # session-scoped, so losing the connection releases the lock and
            # lets another worker take over.
            async with engine.connect() as conn:
                got = (
                    await conn.execute(
                        text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}
                    )
                ).scalar()
                if got:
                    # Advisory locks are session-level — commit so the
                    # connection doesn't sit idle-in-transaction while held.
                    await conn.commit()
                    log.info("%s: acquired leader lock, starting loop", name)
                    await loop_fn()
                    return  # loop_fn only returns if intentionally done
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — guard must never die
            log.warning("%s: leader guard error: %s", name, exc)
        await asyncio.sleep(RETRY_INTERVAL)
