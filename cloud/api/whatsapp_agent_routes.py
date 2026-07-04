"""Agent-facing WhatsApp self-service (plan 034.1).

The machine — i.e. plugin-whatsapp >= 0.7.0 running inside a hosted Luna —
provisions its OWN gateway account with its device token. The gateway admin
key never leaves the control plane; the account id is always the calling
agent's slug (server-enforced). Installing the plugin is the whole setup.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select

from cloud.db import session as db_session
from cloud.db.models import Agent
from cloud.gateway import tokens as token_svc
from cloud.whatsapp import provision

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/whatsapp", tags=["whatsapp-agent"])


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


def _require_gateway() -> str:
    url, _ = provision.gateway_config()
    if not url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp gateway not configured"
        )
    return url


@router.post("/connect")
async def agent_connect(
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    """Create (or assert) THIS machine's WhatsApp account. Returns the
    per-account secret only when newly created/rotated — the plugin stores
    it in its vault. Idempotent."""
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    gateway_url = _require_gateway()

    resp = await provision._gateway("POST", "/accounts", {
        "account_id": agent.slug,
        "inbound_url": provision.relay_inbound_url(agent.slug),
    })
    if resp.status_code not in (200, 201):
        log.error("whatsapp.agent_connect gateway %s: %s", resp.status_code, resp.text[:200])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gateway account creation failed")
    account = resp.json()

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
        "status": account.get("status"),
        "gateway_url": gateway_url,
    }
    if account.get("secret"):
        out["secret"] = account["secret"]
    return out


@router.get("/qr")
async def agent_qr(
    format: str = "html",
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    """THIS machine's account QR, proxied server-side."""
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    _require_gateway()
    fmt = format if format in ("html", "png", "json") else "html"
    try:
        resp = await provision.fetch_account_qr(agent.slug, fmt=fmt)
    except Exception:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gateway unreachable")
    if fmt == "html":
        return HTMLResponse(resp.text, status_code=resp.status_code)
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/octet-stream"),
    )


@router.get("/status")
async def agent_status(
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    """THIS machine's account slice of the gateway state."""
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    _require_gateway()
    try:
        resp = await provision._gateway("GET", f"/accounts/{agent.slug}")
    except Exception:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gateway unreachable")
    if resp.status_code == 404:
        return {"exists": False}
    if resp.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gateway error")
    a = resp.json()
    if isinstance(a, dict) and "account" in a:
        a = a["account"]
    return {
        "exists": True,
        "status": a.get("status"),
        "connected": a.get("connected"),
        "self_jid": a.get("self_jid"),
        "has_qr": a.get("has_qr"),
        "sent_today": a.get("sent_today"),
        "daily_cap": a.get("daily_cap"),
        "messages_24h_in": a.get("messages_24h_in"),
        "messages_24h_out": a.get("messages_24h_out"),
    }


@router.delete("/connect")
async def agent_disconnect(
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    _require_gateway()
    result = await provision.disconnect_agent(agent)
    return {"ok": True, **result}
