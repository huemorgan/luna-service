"""Telegram gateway monitoring and public inbound relay (plan 045)."""

from __future__ import annotations

import logging
import re
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from cloud.auth.deps import require_admin
from cloud.db.models import Agent, User
from cloud.db.session import get_session as get_db_session
from cloud.telegram import provision

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/telegram", tags=["telegram"])

STATS_TIMEOUT_S = 5.0
STATS_CACHE_TTL_S = 12.0
RELAY_TIMEOUT_S = 120.0

_stats_cache: tuple[float, dict] | None = None
_BOT_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
_SENSITIVE_KEY_PARTS = ("token", "secret", "admin_key", "admin-key")


def _redact(value, admin_key: str = ""):
    """Remove credentials even if an upstream error accidentally includes them."""
    if isinstance(value, dict):
        return {
            key: _redact(item, admin_key)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_redact(item, admin_key) for item in value]
    if isinstance(value, str):
        cleaned = value.replace(admin_key, "[redacted]") if admin_key else value
        return _BOT_TOKEN_RE.sub("[redacted]", cleaned)
    return value


async def _fetch_stats(url: str, admin_key: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=STATS_TIMEOUT_S) as client:
            response = await client.get(
                f"{url}/stats", headers={"x-admin-key": admin_key}
            )
    except Exception as exc:
        log.warning(
            "telegram.gateway_unreachable url=%s error_type=%s",
            url,
            type(exc).__name__,
        )
        return {"configured": True, "reachable": False}

    if response.status_code in (401, 403):
        return {"configured": True, "reachable": True, "authorized": False}
    if response.status_code != 200:
        log.warning("telegram.gateway_bad_status status=%s", response.status_code)
        return {"configured": True, "reachable": False}
    try:
        stats = response.json()
    except ValueError:
        return {"configured": True, "reachable": False}
    return {
        "configured": True,
        "reachable": True,
        "authorized": True,
        "stats": provision.normalize_stats(_redact(stats, admin_key)),
    }


async def _cached_stats() -> dict:
    global _stats_cache
    url, admin_key = provision.gateway_config()
    if not url:
        return {"configured": False}
    now = time.monotonic()
    if _stats_cache and _stats_cache[0] > now:
        return _stats_cache[1]
    payload = await _fetch_stats(url, admin_key)
    _stats_cache = (now + STATS_CACHE_TTL_S, payload)
    return payload


@router.get("/stats")
async def gateway_stats(admin=Depends(require_admin)):
    return await _cached_stats()


def _account_view(account: dict) -> dict:
    normalized = provision.normalize_account(account)
    normalized.pop("account_id", None)
    return normalized


@router.get("/instances")
async def telegram_instances(admin=Depends(require_admin)):
    payload = await _cached_stats()
    accounts = (payload.get("stats") or {}).get("accounts") or []
    accounts_by_id = {
        account.get("account_id"): account
        for account in accounts
        if isinstance(account, dict) and account.get("account_id")
    }
    async with get_db_session() as db:
        agents = (
            await db.execute(select(Agent).order_by(Agent.created_at))
        ).scalars().all()
        return [
            {
                "agent_id": str(agent.id),
                "name": agent.name,
                "slug": agent.slug,
                "status": agent.status,
                "plugin_installed": provision.PLUGIN_NAME
                in ((agent.config_overrides or {}).get("installed_plugins") or []),
                "account": _account_view(accounts_by_id[agent.slug])
                if agent.slug in accounts_by_id
                else None,
            }
            for agent in agents
        ]


relay_router = APIRouter(tags=["telegram-relay"])


@relay_router.post("/api/webhooks/telegram/{agent_slug}/inbound")
async def telegram_inbound_relay(agent_slug: str, request: Request):
    import os

    from cloud.api.proxy import _try_wake_agent
    from cloud.runtime.proxy_secret import derive_proxy_secret

    async with get_db_session() as db:
        agent = (
            await db.execute(select(Agent).where(Agent.slug == agent_slug))
        ).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown agent")
        owner = (
            await db.execute(select(User).where(User.id == agent.creator_id))
        ).scalar_one_or_none()

    if not (agent.internal_url or "").startswith(("http://", "https://")):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Agent has no machine"
        )

    raw = await request.body()
    root_secret = os.environ.get(
        "CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret"
    )
    headers = {
        "content-type": request.headers.get("content-type", "application/json"),
        "x-tg-account": request.headers.get("x-tg-account", ""),
        "x-tg-timestamp": request.headers.get("x-tg-timestamp", ""),
        "x-tg-signature": request.headers.get("x-tg-signature", ""),
        "x-luna-proxy-secret": derive_proxy_secret(root_secret, str(agent.id)),
        "x-luna-user": (owner.email if owner else "") or "",
    }
    if agent.runtime_ref:
        headers["fly-force-instance-id"] = agent.runtime_ref
    target = (
        f"{(agent.internal_url or '').rstrip('/')}"
        "/api/p/plugin-telegram/inbound"
    )

    async def _send():
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(RELAY_TIMEOUT_S, connect=10)
        ) as client:
            return await client.post(target, content=raw, headers=headers)

    try:
        response = await _send()
    except httpx.ReadTimeout:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, "Agent turn timed out"
        )
    except httpx.HTTPError:
        if not await _try_wake_agent(agent):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "Agent unreachable"
            )
        try:
            response = await _send()
        except Exception:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "Agent unreachable after wake"
            )

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json"),
    )
