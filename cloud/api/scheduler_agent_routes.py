"""Agent-facing scheduler self-service (plan 035, 034.1 pattern).

The machine — i.e. plugin-scheduler running inside a hosted Luna — provisions
its OWN scheduler-service account with its device token. The service admin
key never leaves the control plane; the account id is always the calling
agent's slug (server-enforced). Installing the plugin is the whole setup.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Header, HTTPException, status
from sqlalchemy import select

from cloud.db import session as db_session
from cloud.db.models import Agent
from cloud.gateway import tokens as token_svc
from cloud.scheduler_svc import provision

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/scheduler", tags=["scheduler-agent"])


def _bearer(authorization: str | None, x_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_token


async def _agent_from_token(
    authorization: str | None, x_token: str | None
) -> Agent:
    token = _bearer(authorization, x_token)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing device token")
    async with db_session.get_session() as db:
        agent_id = await token_svc.verify_token(db, token)
        if agent_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid device token")
        agent = (await db.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown agent")
        return agent


def _require_service() -> str:
    url, _ = provision.service_config()
    if not url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Scheduler service not configured"
        )
    return url


@router.post("/connect")
async def agent_connect(
    payload: dict | None = Body(default=None),
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    """Create (or assert) THIS machine's scheduler account. Returns the
    per-account secret only when newly created/rotated — the plugin stores
    it in its vault. Idempotent.

    ``{"rotate": true}`` recovers a lost secret (vault wiped, machine
    rebuilt): the account already exists, so plain connect returns no
    secret; rotate mints a fresh one via the service and returns it once.
    Safe — the device token already proves this is the account's machine,
    and rotation invalidates only the lost secret."""
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    service_url = _require_service()

    resp = await provision._service("POST", "/accounts", {
        "account_id": agent.slug,
        "fire_url": provision.relay_fire_url(agent.slug),
    })
    if resp.status_code not in (200, 201):
        log.error("scheduler.agent_connect service %s: %s", resp.status_code, resp.text[:200])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Scheduler account creation failed")
    account = resp.json()

    secret = account.get("secret")
    if (payload or {}).get("rotate") and not secret:
        rot = await provision._service(
            "PATCH", f"/accounts/{agent.slug}", {"rotate_secret": True}
        )
        if rot.status_code != 200:
            log.error("scheduler.agent_rotate service %s: %s", rot.status_code, rot.text[:200])
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Scheduler secret rotation failed")
        secret = rot.json().get("secret")

    # Keep the admin monitoring table truthful about who runs the plugin.
    async with db_session.get_session() as db:
        row = (await db.execute(
            select(Agent).where(Agent.id == agent.id)
        )).scalar_one()
        overrides = dict(row.config_overrides or {})
        installed = list(overrides.get("installed_plugins") or [])
        if provision.PLUGIN_NAME not in installed:
            installed.append(provision.PLUGIN_NAME)
            overrides["installed_plugins"] = installed
            row.config_overrides = overrides
            await db.commit()

    out = {
        "account_id": account.get("account_id", agent.slug),
        "created": account.get("created"),
        "service_url": service_url,
    }
    if secret:
        out["secret"] = secret
    return out


@router.get("/status")
async def agent_status(
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    """THIS machine's account slice of the service state."""
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    _require_service()
    try:
        resp = await provision._service("GET", f"/accounts/{agent.slug}")
    except Exception:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Scheduler service unreachable")
    if resp.status_code == 404:
        return {"exists": False}
    if resp.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Scheduler service error")
    a = resp.json()
    if isinstance(a, dict) and "account" in a:
        a = a["account"]
    return {
        "exists": True,
        "enabled": a.get("enabled"),
        "triggers": a.get("triggers"),
        "next_run_at": a.get("next_run_at"),
        "last_fire_at": a.get("last_fire_at"),
        "last_fire_status": a.get("last_fire_status"),
        "fires_24h": a.get("fires_24h"),
        "sent_today": a.get("sent_today"),
        "daily_cap": a.get("daily_cap"),
    }


@router.delete("/connect")
async def agent_disconnect(
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    _require_service()
    result = await provision.disconnect_agent(agent)
    return {"ok": True, **result}
