"""WhatsApp gateway monitoring — admin proxy to luna-wa-gateway (plan 034).

The gateway's ``GET /stats`` is admin-key protected; the key lives only in
control-plane config and never reaches the browser. Responses are cached
in-process for a few seconds so N polling admin tabs produce at most one
upstream request per TTL window.
"""

from __future__ import annotations

import logging
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from cloud import config
from cloud.auth.deps import require_admin
from cloud.db.models import Agent, User
from cloud.db.session import get_session as get_db_session
from cloud.whatsapp import provision

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
    _stats_cache = (now + STATS_CACHE_TTL_S, payload)
    return payload


async def _accounts_by_id() -> dict[str, dict]:
    """Per-account state from the gateway's /stats (multi-account), keyed by
    account_id. Empty when unconfigured/unreachable — the table degrades to
    readiness-only."""
    url, admin_key = provision.gateway_config()
    if not url:
        return {}
    payload = await _fetch_stats(url, admin_key)
    accounts = (payload.get("stats") or {}).get("accounts") or []
    return {a.get("account_id"): a for a in accounts if a.get("account_id")}


@router.get("/instances")
async def whatsapp_instances(admin=Depends(require_admin)):
    """Per-Luna WhatsApp state: plugin membership + the agent's own gateway
    account (account_id == agent.slug)."""
    accounts = await _accounts_by_id()
    async with get_db_session() as db:
        agents = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
        rows = []
        for a in agents:
            acct = accounts.get(a.slug)
            rows.append({
                "agent_id": str(a.id),
                "name": a.name,
                "slug": a.slug,
                "status": a.status,
                "plugin_installed": "plugin-whatsapp"
                in ((a.config_overrides or {}).get("installed_plugins") or []),
                "account": {
                    "status": acct.get("status"),
                    "connected": acct.get("connected"),
                    "self_jid": acct.get("self_jid"),
                    "has_qr": acct.get("has_qr"),
                    "messages_24h_in": acct.get("messages_24h_in"),
                    "messages_24h_out": acct.get("messages_24h_out"),
                    "sent_today": acct.get("sent_today"),
                    "daily_cap": acct.get("daily_cap"),
                } if acct else None,
            })
        return rows


# ── Public inbound relay ─────────────────────────────────────────────────────
# The gateway POSTs each account's inbound envelope here (this URL is what
# connect registers as the account's inbound_url). We forward the RAW bytes +
# HMAC headers to the tenant machine — Fly routing header, wake-on-sleep —
# and the plugin verifies the signature itself. No session auth by design:
# a forged request without the account secret dies at the plugin's HMAC check.

RELAY_TIMEOUT_S = 120.0  # gateway tolerates slow (cold-start) turns up to 120s


relay_router = APIRouter(tags=["whatsapp-relay"])


@relay_router.post("/api/webhooks/whatsapp/{agent_slug}/inbound")
async def whatsapp_inbound_relay(agent_slug: str, request: Request):
    import os

    from cloud.api.proxy import _try_wake_agent
    from cloud.runtime.proxy_secret import derive_proxy_secret

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.slug == agent_slug)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown agent")
        owner = (await db.execute(
            select(User).where(User.id == agent.creator_id)
        )).scalar_one_or_none()

    if not (agent.internal_url or "").startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent has no machine")

    raw = await request.body()
    root_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")
    headers = {
        "content-type": request.headers.get("content-type", "application/json"),
        "x-wa-timestamp": request.headers.get("x-wa-timestamp", ""),
        "x-wa-signature": request.headers.get("x-wa-signature", ""),
        "x-luna-proxy-secret": derive_proxy_secret(root_secret, str(agent.id)),
        "x-luna-user": (owner.email if owner else "") or "",
    }
    if agent.runtime_ref:
        headers["fly-force-instance-id"] = agent.runtime_ref
    target = f"{(agent.internal_url or '').rstrip('/')}/api/p/plugin-whatsapp/inbound"

    async def _send():
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(RELAY_TIMEOUT_S, connect=10)
        ) as client:
            return await client.post(target, content=raw, headers=headers)

    try:
        resp = await _send()
    except httpx.ReadTimeout:
        # NOT retried — the turn may still be running; a retry risks a double reply.
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Agent turn timed out")
    except httpx.HTTPError:
        # Machine asleep/unreachable — wake it and retry once.
        if not await _try_wake_agent(agent):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Agent unreachable")
        try:
            resp = await _send()
        except Exception:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Agent unreachable after wake")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )
