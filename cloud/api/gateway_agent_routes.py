"""Agent-facing gateway discovery (plan 026.1).

One endpoint, authed by the machine's device token (lsv1-…), that returns the
inventory of gateway services for the calling agent — what it's *provisioned*
for (its virtual keys) and what's *available* to add. Secrets-free: never
returns a key value. Consumed by the luna vault (to project virtual keys) and by
the agent's self-service tools. See proposal `026.1-vault-virtual-keys.md`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from cloud.config import get_settings
from cloud.db import session as db_session
from cloud.db.models import Agent, GatewayService, PluginCatalogEntry
from cloud.gateway import tokens as token_svc
from cloud.gateway.catalog import effective_plugin_names
from cloud.gateway.keys import has_active_key
from cloud.gateway.registry import parse_auth_style

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/gateway", tags=["gateway-agent"])


def _bearer(authorization: str | None, x_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_token


@router.get("/services")
async def discover_services(
    request: Request,
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    token = _bearer(authorization, x_luna_gateway_token)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing device token")

    base = get_settings().base_url.rstrip("/")
    async with db_session.get_session() as db:
        agent_id = await token_svc.verify_token(db, token)
        if agent_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid device token")

        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown agent")

        # Effective plugins for this agent need the image's baked plugin_set.
        from cloud.api.gateway_env_delta import _agent_image_config
        image_config = await _agent_image_config(db, agent)
        plugin_names = effective_plugin_names(image_config, agent.config_overrides)

        services = (await db.execute(
            select(GatewayService).where(GatewayService.enabled.is_(True))
        )).scalars().all()
        svc_by_slug = {s.slug: s for s in services}

        catalog = (await db.execute(
            select(PluginCatalogEntry).where(
                PluginCatalogEntry.enabled.is_(True),
                PluginCatalogEntry.service_slug.isnot(None),
            )
        )).scalars().all()

        # slug → True when some plugin this agent runs binds it (its virtual keys).
        provisioned_slugs: set[str] = set()
        purpose_by_slug: dict[str, str] = {}
        advertised: set[str] = set()
        for entry in catalog:
            slug = entry.service_slug
            if slug not in svc_by_slug:
                continue
            advertised.add(slug)
            if entry.category and slug not in purpose_by_slug:
                purpose_by_slug[slug] = entry.category
            if entry.plugin_name.strip().lower() in plugin_names:
                provisioned_slugs.add(slug)

        # LLM/base services provisioned by default are always-on virtual keys.
        for s in services:
            if s.provision_by_default:
                advertised.add(s.slug)
                provisioned_slugs.add(s.slug)

        out = []
        for slug in sorted(advertised):
            svc = svc_by_slug[slug]
            try:
                auth = parse_auth_style(svc.auth_style)
            except ValueError:
                auth = None
            has_key = await has_active_key(db, slug, agent_id)
            provisioned = slug in provisioned_slugs
            out.append({
                "slug": slug,
                "display_name": svc.display_name,
                "purpose": purpose_by_slug.get(slug, svc.display_name),
                "proxy_url": f"{base}/proxy/{slug}",
                "auth_header": auth.header if auth else None,
                "auth_scheme": auth.scheme if auth else None,
                "auth_location": auth.location if auth else "header",
                "provisioned": provisioned,
                "has_key": has_key,
                "status": "active" if (provisioned and has_key) else "available",
            })
    return out
