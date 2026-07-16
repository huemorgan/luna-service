"""Tenant-authenticated Telegram self-service (plan 045)."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from cloud.db import session as db_session
from cloud.db.models import Agent
from cloud.gateway import tokens as token_svc
from cloud.telegram import provision

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/telegram", tags=["telegram-agent"])


class ConnectRequest(BaseModel):
    bot_token: str = Field(min_length=1)


def _bearer(authorization: str | None, x_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_token


async def _agent_from_token(
    authorization: str | None, x_token: str | None
) -> Agent:
    token = _bearer(authorization, x_token)
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing device token"
        )
    async with db_session.get_session() as db:
        agent_id = await token_svc.verify_token(db, token)
        if agent_id is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Invalid device token"
            )
        agent = (
            await db.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown agent")
        return agent


def _require_gateway() -> str:
    url, _ = provision.gateway_config()
    if not url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Telegram gateway not configured",
        )
    return url


def _gateway_error(response) -> tuple[str, str]:
    try:
        payload = response.json()
    except ValueError:
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or ""), str(
            error.get("message") or error.get("detail") or ""
        )
    return str(payload.get("code") or error or ""), str(
        payload.get("message") or payload.get("detail") or ""
    )


@router.post("/connect")
async def agent_connect(
    payload: ConnectRequest,
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    gateway_url = _require_gateway()
    try:
        response = await provision._gateway(
            "POST",
            "/accounts",
            {
                "account_id": agent.slug,
                "bot_token": payload.bot_token,
                "inbound_url": provision.relay_inbound_url(agent.slug),
            },
        )
    except httpx.HTTPError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Telegram gateway unreachable"
        )

    if response.status_code in (400, 422):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid BotFather token"
        )
    if response.status_code == 409:
        code, message = _gateway_error(response)
        if "bot_already_connected" in f"{code} {message}".lower():
            detail = "This Telegram bot is already connected to another Luna"
        else:
            detail = "Telegram account conflict"
        raise HTTPException(status.HTTP_409_CONFLICT, detail)
    if response.status_code == 503:
        code, message = _gateway_error(response)
        if "public_url" in f"{code} {message}".lower():
            detail = "Telegram gateway public URL is not configured"
        else:
            detail = "Telegram gateway is unavailable"
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    if response.status_code in (401, 403):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Telegram gateway authorization failed",
        )
    if response.status_code not in (200, 201):
        log.error(
            "telegram.agent_connect gateway_status=%s", response.status_code
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Telegram account creation failed",
        )
    try:
        body = response.json()
    except ValueError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Invalid Telegram gateway response"
        )
    account = body.get("account") if isinstance(body, dict) else None
    if not isinstance(account, dict) or body.get("ok") is False:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Invalid Telegram gateway response"
        )
    normalized = provision.normalize_account(account)

    async with db_session.get_session() as db:
        row = (
            await db.execute(select(Agent).where(Agent.id == agent.id))
        ).scalar_one()
        overrides = dict(row.config_overrides or {})
        installed = list(overrides.get("installed_plugins") or [])
        if provision.PLUGIN_NAME not in installed:
            installed.append(provision.PLUGIN_NAME)
            overrides["installed_plugins"] = installed
            row.config_overrides = overrides
            await db.commit()

    result = {
        "account_id": agent.slug,
        "gateway_url": gateway_url,
        "bot": normalized["bot"],
        "status": normalized.get("status"),
    }
    shared_secret = body.get("shared_secret")
    if isinstance(shared_secret, str) and shared_secret:
        result["shared_secret"] = shared_secret
    return result


@router.get("/status")
async def agent_status(
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    _require_gateway()
    try:
        response = await provision._gateway(
            "GET", f"/accounts/{agent.slug}"
        )
    except httpx.HTTPError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Telegram gateway unreachable"
        )
    if response.status_code == 404:
        return {"exists": False}
    if response.status_code in (401, 403):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Telegram gateway authorization failed",
        )
    if response.status_code != 200:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Telegram gateway error"
        )
    try:
        body = response.json()
    except ValueError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Invalid Telegram gateway response"
        )
    account = body.get("account") if isinstance(body, dict) else None
    if account is None and isinstance(body, dict):
        account = body
    if not isinstance(account, dict):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Invalid Telegram gateway response"
        )
    result = {"exists": True, **provision.normalize_account(account)}
    result["account_id"] = agent.slug
    return result


@router.delete("/connect")
async def agent_disconnect(
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    _require_gateway()
    try:
        result = await provision.disconnect_agent(agent)
    except httpx.HTTPError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Telegram gateway unreachable"
        )
    if result["status_code"] in (401, 403):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Telegram gateway authorization failed",
        )
    if result["status_code"] not in (200, 204, 404):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Telegram gateway error"
        )
    return {"ok": True, **result}
