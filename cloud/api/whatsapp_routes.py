"""WhatsApp gateway monitoring — admin proxy to luna-wa-gateway (plan 034).

The gateway's ``GET /stats`` is admin-key protected; the key lives only in
control-plane config and never reaches the browser. Responses are cached
in-process for a few seconds so N polling admin tabs produce at most one
upstream request per TTL window.
"""

from __future__ import annotations

import logging
import time

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select

from cloud import config
from cloud.auth.deps import require_admin
from cloud.db.models import Agent
from cloud.db.session import get_session as get_db_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/whatsapp", tags=["whatsapp"])

STATS_TIMEOUT_S = 5.0
STATS_CACHE_TTL_S = 12.0

# (expires_at_monotonic, payload) — payload is the full route response.
_stats_cache: tuple[float, dict] | None = None


def _gateway_config() -> tuple[str, str]:
    s = config.get_settings()
    return s.whatsapp_gateway_url.rstrip("/"), s.whatsapp_gateway_admin_key


async def _fetch_stats(url: str, admin_key: str) -> dict:
    """One upstream call, mapped to a never-5xx envelope."""
    try:
        async with httpx.AsyncClient(timeout=STATS_TIMEOUT_S) as client:
            resp = await client.get(
                f"{url}/stats", headers={"x-admin-key": admin_key}
            )
    except Exception as exc:  # DNS, timeout, refused — the page shows Offline
        log.warning("whatsapp.stats_unreachable url=%s err=%s", url, exc)
        return {"configured": True, "reachable": False}

    if resp.status_code == 401:
        return {"configured": True, "reachable": True, "authorized": False}
    if resp.status_code != 200:
        log.warning("whatsapp.stats_bad_status status=%s", resp.status_code)
        return {"configured": True, "reachable": False}
    try:
        stats = resp.json()
    except ValueError:
        return {"configured": True, "reachable": False}
    return {
        "configured": True,
        "reachable": True,
        "authorized": True,
        "stats": stats,
    }


@router.get("/stats")
async def gateway_stats(admin=Depends(require_admin)):
    global _stats_cache
    url, admin_key = _gateway_config()
    if not url:
        return {"configured": False}

    now = time.monotonic()
    if _stats_cache and _stats_cache[0] > now:
        return _stats_cache[1]

    payload = await _fetch_stats(url, admin_key)
    # QR is served through our own authed proxy — the admin key never
    # appears in a browser-visible URL.
    payload["qr_url"] = (
        "/api/admin/whatsapp/qr" if payload.get("stats", {}).get("has_qr") else None
    )
    _stats_cache = (now + STATS_CACHE_TTL_S, payload)
    return payload


@router.get("/qr")
async def gateway_qr(admin=Depends(require_admin)):
    """Server-side proxy of the gateway's QR page (it self-refreshes, so
    each refresh comes back through this authed route)."""
    from fastapi.responses import HTMLResponse

    url, admin_key = _gateway_config()
    if not url:
        return HTMLResponse("<p>WhatsApp gateway not configured.</p>", status_code=503)
    try:
        async with httpx.AsyncClient(timeout=STATS_TIMEOUT_S) as client:
            resp = await client.get(f"{url}/qr", params={"key": admin_key})
    except Exception:
        return HTMLResponse("<p>Gateway unreachable.</p>", status_code=502)
    return HTMLResponse(resp.text, status_code=resp.status_code)


@router.get("/instances")
async def whatsapp_instances(admin=Depends(require_admin)):
    """Control-plane view of WhatsApp readiness per agent.

    v1 reports plugin membership from ``config_overrides.installed_plugins``.
    Per-account link status joins in once the multi-account gateway ships
    (`multi-luna-gateway-ask.md`).
    """
    async with get_db_session() as db:
        agents = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
        return [
            {
                "agent_id": str(a.id),
                "name": a.name,
                "slug": a.slug,
                "status": a.status,
                "plugin_installed": "plugin-whatsapp"
                in ((a.config_overrides or {}).get("installed_plugins") or []),
            }
            for a in agents
        ]
