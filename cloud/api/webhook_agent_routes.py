"""Agent-facing webhook minting (plan 076, 035 pattern).

A plugin running inside a hosted Luna mints its own inbound-webhook URLs
with its device token. The hook's per-endpoint secret is returned only on
create/rotate — the plugin stores it in its vault and verifies each
delivery's HMAC itself. The public URL identifies the agent by slug and the
hook by an unguessable token; the ingress does no auth of its own beyond
that (same trust model as the scheduler fire relay, plan 035 D3).
"""

from __future__ import annotations

import logging
import re
import secrets as pysecrets

from fastapi import APIRouter, Body, Header, HTTPException, status
from sqlalchemy import select

from cloud.db import session as db_session
from cloud.db.models import Agent, WebhookEndpoint
from cloud.gateway import tokens as token_svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/webhooks", tags=["webhooks-agent"])

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PLUGIN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def public_hook_url(agent_slug: str, hook_slug: str) -> str:
    from cloud.config import get_settings

    settings = get_settings()
    base = getattr(settings, "webhooks_base_url", None) or settings.base_url
    return f"{base.rstrip('/')}/api/webhooks/hooks/{agent_slug}/{hook_slug}"


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


def _endpoint_out(ep: WebhookEndpoint, agent_slug: str) -> dict:
    return {
        "name": ep.name,
        "plugin": ep.plugin,
        "hook_slug": ep.hook_slug,
        "public_url": public_hook_url(agent_slug, ep.hook_slug),
        "target_path": ep.target_path,
        "mode": ep.mode,
        "enabled": ep.enabled,
        "created_at": ep.created_at.isoformat() if ep.created_at else None,
        "last_delivery_at": ep.last_delivery_at.isoformat() if ep.last_delivery_at else None,
        "delivery_count": ep.delivery_count,
        "last_status_code": ep.last_status_code,
    }


@router.post("/hooks")
async def create_hook(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    """Create (or assert) a hook for THIS agent. Idempotent on
    (plugin, name); the secret is returned only when newly created or when
    ``{"rotate": true}`` is passed."""
    agent = await _agent_from_token(authorization, x_luna_gateway_token)

    name = str(payload.get("name") or "").strip().lower()
    plugin = str(payload.get("plugin") or "").strip().lower()
    target_path = str(payload.get("target_path") or "").strip()
    mode = str(payload.get("mode") or "sync").strip().lower()
    rotate = bool(payload.get("rotate"))

    if not _NAME_RE.match(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid hook name")
    if not _PLUGIN_RE.match(plugin):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid plugin name")
    if not target_path.startswith("/api/p/") or ".." in target_path or len(target_path) > 512:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "target_path must start with /api/p/"
        )
    if mode not in ("sync", "queue"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "mode must be sync or queue")

    async with db_session.get_session() as db:
        ep = (await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.agent_id == agent.id,
                WebhookEndpoint.plugin == plugin,
                WebhookEndpoint.name == name,
            )
        )).scalar_one_or_none()

        secret: str | None = None
        created = ep is None
        if created:
            secret = pysecrets.token_urlsafe(32)
            ep = WebhookEndpoint(
                agent_id=agent.id,
                hook_slug=pysecrets.token_urlsafe(18),
                name=name,
                plugin=plugin,
                target_path=target_path,
                mode=mode,
                secret=secret,
            )
            db.add(ep)
        else:
            ep.target_path = target_path
            ep.mode = mode
            if rotate:
                secret = pysecrets.token_urlsafe(32)
                ep.secret = secret

        # Keep the admin monitoring table truthful about who mints hooks.
        agent_row = (await db.execute(
            select(Agent).where(Agent.id == agent.id)
        )).scalar_one()
        overrides = dict(agent_row.config_overrides or {})
        installed = list(overrides.get("installed_plugins") or [])
        if plugin not in installed:
            installed.append(plugin)
            overrides["installed_plugins"] = installed
            agent_row.config_overrides = overrides

        await db.commit()
        await db.refresh(ep)

        out = _endpoint_out(ep, agent.slug)
        out["created"] = created
        if secret:
            out["secret"] = secret
        return out


@router.get("/hooks")
async def list_hooks(
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    async with db_session.get_session() as db:
        eps = (await db.execute(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.agent_id == agent.id)
            .order_by(WebhookEndpoint.created_at)
        )).scalars().all()
        return {"hooks": [_endpoint_out(ep, agent.slug) for ep in eps]}


@router.patch("/hooks/{hook_slug}")
async def update_hook(
    hook_slug: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    async with db_session.get_session() as db:
        ep = (await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.hook_slug == hook_slug,
                WebhookEndpoint.agent_id == agent.id,
            )
        )).scalar_one_or_none()
        if not ep:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown hook")
        if "enabled" in payload:
            ep.enabled = bool(payload["enabled"])
        await db.commit()
        await db.refresh(ep)
        return _endpoint_out(ep, agent.slug)


@router.delete("/hooks/{hook_slug}")
async def delete_hook(
    hook_slug: str,
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    async with db_session.get_session() as db:
        ep = (await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.hook_slug == hook_slug,
                WebhookEndpoint.agent_id == agent.id,
            )
        )).scalar_one_or_none()
        if not ep:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown hook")
        await db.delete(ep)
        await db.commit()
        return {"ok": True}
