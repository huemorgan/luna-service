"""Fly-status reconciliation sweep (plan 037-SPEED101, phase 1).

Agents whose Fly machine died or was destroyed keep status='running' in the
DB forever ("ghosts"); every dashboard load then burns a full proxy timeout
per ghost. This sweep aligns DB status with actual machine state.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select

from cloud.db.models import Agent
from cloud.db.session import get_session

log = logging.getLogger(__name__)

INTERVAL = int(os.environ.get("CLOUD_RECONCILE_INTERVAL", "60"))


async def reconcile_once(fly) -> int:
    """One sweep: mark running agents whose machine is gone/stopped. Returns #changed."""
    machines = {m["id"]: m.get("state", "") for m in await fly.list_machines()}
    changed = 0
    async with get_session() as db:
        agents = (
            await db.execute(select(Agent).where(Agent.status == "running"))
        ).scalars().all()
        for a in agents:
            if not a.runtime_ref:
                continue
            state = machines.get(a.runtime_ref)
            if state is None or state in ("destroying", "destroyed"):
                a.status = "error"
                a.error_message = "Machine no longer exists (reconciler)"
                a.error_at = datetime.now(timezone.utc)
                changed += 1
                log.info("Reconciler: agent %s machine %s gone → error", a.slug, a.runtime_ref)
            elif state in ("stopped", "suspended"):
                a.status = "stopped"
                changed += 1
                log.info("Reconciler: agent %s machine %s %s → stopped", a.slug, a.runtime_ref, state)
        if changed:
            await db.commit()
    return changed


async def reconcile_loop() -> None:
    if not os.environ.get("FLY_API_TOKEN"):
        log.info("Reconciler disabled: no FLY_API_TOKEN")
        return
    from cloud.runtime.fly_machines import FlyMachinesRuntime

    fly = FlyMachinesRuntime()
    while True:
        try:
            await reconcile_once(fly)
        except Exception as exc:  # noqa: BLE001 — sweep must never die
            log.warning("Reconcile sweep failed: %s", exc)
        await asyncio.sleep(INTERVAL)
