"""Orphaned scheduler-account sweep (plan 078/7a).

Teardown now disconnects an agent's scheduler account, but accounts orphaned
before that fix — and any teardown whose disconnect call failed — keep firing
their triggers on the external service forever (the 08-31→09-04 gateway_auth
zombie grids). This sweep reconciles the service's account list against live
agents: an account whose id (== agent slug) has no non-deleted agent row is
deleted from the service.

Runs in one worker (advisory-lock guarded from the lifespan), first pass at
boot, then every ``INTERVAL_S``.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from cloud.db.models import Agent
from cloud.db.session import get_session as get_db_session
from cloud.scheduler_svc import provision

log = logging.getLogger(__name__)

INTERVAL_S = 6 * 3600


async def sweep_once() -> dict:
    """One reconciliation pass. Returns counts for tests/observability."""
    url, admin_key = provision.service_config()
    if not url:
        return {"skipped": "unconfigured"}

    import httpx

    async with httpx.AsyncClient(timeout=provision.SERVICE_TIMEOUT_S) as client:
        resp = await client.get(f"{url}/stats", headers={"x-admin-key": admin_key})
    if resp.status_code != 200:
        log.warning("scheduler sweep: /stats returned %s", resp.status_code)
        return {"skipped": f"stats {resp.status_code}"}
    accounts = (resp.json() or {}).get("accounts") or []
    slugs = [a.get("account_id") for a in accounts if a.get("account_id")]
    if not slugs:
        return {"accounts": 0, "orphaned": 0, "deleted": 0}

    async with get_db_session() as db:
        live = set(
            (await db.execute(
                select(Agent.slug).where(
                    Agent.slug.in_(slugs),
                    Agent.deleted_at.is_(None),
                )
            )).scalars().all()
        )
    orphaned = [s for s in slugs if s not in live]

    deleted = 0
    for slug in orphaned:
        try:
            async with httpx.AsyncClient(timeout=provision.SERVICE_TIMEOUT_S) as client:
                resp = await client.delete(
                    f"{url}/accounts/{slug}", headers={"x-admin-key": admin_key}
                )
            if resp.status_code in (200, 204, 404):
                deleted += 1
                log.info("scheduler sweep: removed orphaned account %s (%s)",
                         slug, resp.status_code)
            else:
                log.warning("scheduler sweep: delete %s returned %s",
                            slug, resp.status_code)
        except Exception as exc:  # noqa: BLE001 — keep sweeping the rest
            log.warning("scheduler sweep: delete %s failed: %s", slug, exc)
    return {"accounts": len(slugs), "orphaned": len(orphaned), "deleted": deleted}


async def sweep_loop() -> None:
    while True:
        try:
            result = await sweep_once()
            if result.get("orphaned"):
                log.info("scheduler sweep: %s", result)
        except Exception as exc:  # noqa: BLE001 — sweep must never die
            log.warning("scheduler sweep failed: %s", exc)
        await asyncio.sleep(INTERVAL_S)
