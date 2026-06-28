"""Admin API for the plugin↔key catalog (plan 026).

Two lists (`tier`): **default** (mirrors the baked plugin_set, keyed so baked
plugins start connected) and **supported** (opt-in catalog, provisioned on
install). Each entry binds a plugin to a GatewayService whose pool key it uses,
in `proxy` mode (token + base-url, key stays server-side) or `env` mode (real
key on the machine — admin opt-in). The smart suggester pre-fills the service.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from cloud.auth.deps import require_admin
from cloud.db import session as db_session
from cloud.db.models import Agent, AuditLog, GatewayService, PluginCatalogEntry, User
from cloud.gateway.keys import has_active_key
from cloud.gateway.registry import service_slug_for_plugin, suggest_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/plugin-catalog", tags=["plugin-catalog"])

_VALID_TIERS = {"default", "supported"}
_VALID_KEY_MODES = {"proxy", "env"}


def _audit(db, *, actor: User, action: str, target: str, metadata: dict | None = None):
    db.add(AuditLog(actor_user_id=actor.id, action=action, target=target, metadata_=metadata))


class CatalogCreate(BaseModel):
    plugin_name: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str | None = None
    marketplace_url: str | None = None
    category: str | None = None
    tier: str = "default"
    service_slug: str | None = None
    key_mode: str = "proxy"


class CatalogUpdate(BaseModel):
    display_name: str | None = None
    marketplace_url: str | None = None
    category: str | None = None
    tier: str | None = None
    service_slug: str | None = None
    key_mode: str | None = None
    enabled: bool | None = None


class InstallRequest(BaseModel):
    agent_id: str
    plugin_name: str


def _entry_dict(e: PluginCatalogEntry, *, has_key: bool = False) -> dict:
    return {
        "plugin_name": e.plugin_name,
        "display_name": e.display_name,
        "marketplace_url": e.marketplace_url,
        "category": e.category,
        "tier": e.tier,
        "service_slug": e.service_slug,
        "key_mode": e.key_mode,
        "suggested": e.suggested,
        "enabled": e.enabled,
        # green "keyed" badge when the bound service has an active pool key.
        "keyed": bool(e.service_slug) and has_key,
    }


def _validate(tier: str | None, key_mode: str | None) -> None:
    if tier is not None and tier not in _VALID_TIERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"tier must be one of {sorted(_VALID_TIERS)}")
    if key_mode is not None and key_mode not in _VALID_KEY_MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"key_mode must be one of {sorted(_VALID_KEY_MODES)}")


async def _service_key_presence(db, slugs: set[str]) -> dict[str, bool]:
    return {s: await has_active_key(db, s) for s in slugs if s}


# ── Suggester ────────────────────────────────────────────────────────────────

@router.get("/suggest")
async def suggest(plugin_name: str = Query(...), admin: User = Depends(require_admin)):
    """One-click GatewayService proposal for a plugin (known slug → filled)."""
    return suggest_service(plugin_name)


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("")
async def list_catalog(
    tier: str | None = Query(default=None),
    admin: User = Depends(require_admin),
):
    _validate(tier, None)
    async with db_session.get_session() as db:
        q = select(PluginCatalogEntry).order_by(PluginCatalogEntry.tier, PluginCatalogEntry.plugin_name)
        if tier:
            q = q.where(PluginCatalogEntry.tier == tier)
        entries = (await db.execute(q)).scalars().all()
        presence = await _service_key_presence(db, {e.service_slug for e in entries if e.service_slug})
    return [_entry_dict(e, has_key=presence.get(e.service_slug, False)) for e in entries]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_catalog(body: CatalogCreate, request: Request, admin: User = Depends(require_admin)):
    _validate(body.tier, body.key_mode)
    async with db_session.get_session() as db:
        existing = (await db.execute(
            select(PluginCatalogEntry).where(PluginCatalogEntry.plugin_name == body.plugin_name)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, f"'{body.plugin_name}' already in catalog")

        if body.service_slug:
            svc = (await db.execute(
                select(GatewayService).where(GatewayService.slug == body.service_slug)
            )).scalar_one_or_none()
            if not svc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown service '{body.service_slug}'")

        suggestion = suggest_service(body.plugin_name, display_name=body.display_name)
        # Auto-bind the suggested service only if it's a registered GatewayService.
        # The suggester knows the slug a plugin *wants* (e.g. "monday"), but that
        # service may not exist in the pool yet — binding it anyway would violate
        # the service_slug FK. Leave it null in that case; the suggestion still
        # rides along in `suggested`, and the admin binds a real service from the
        # row's key picker once it's registered.
        resolved_slug = body.service_slug
        if not resolved_slug and not suggestion["needs_review"]:
            suggested_exists = (await db.execute(
                select(GatewayService).where(GatewayService.slug == suggestion["slug"])
            )).scalar_one_or_none()
            if suggested_exists:
                resolved_slug = suggestion["slug"]
        entry = PluginCatalogEntry(
            plugin_name=body.plugin_name,
            display_name=body.display_name or suggestion["display_name"],
            marketplace_url=body.marketplace_url,
            category=body.category,
            tier=body.tier,
            service_slug=resolved_slug,
            key_mode=body.key_mode,
            suggested=suggestion,
        )
        db.add(entry)
        _audit(db, actor=admin, action="plugin_catalog.created", target=body.plugin_name,
               metadata={"tier": body.tier, "service_slug": entry.service_slug})
        await db.commit()
        presence = await _service_key_presence(db, {entry.service_slug} if entry.service_slug else set())
        return _entry_dict(entry, has_key=presence.get(entry.service_slug, False))


@router.patch("/{plugin_name}")
async def update_catalog(
    plugin_name: str, body: CatalogUpdate, admin: User = Depends(require_admin),
):
    _validate(body.tier, body.key_mode)
    async with db_session.get_session() as db:
        entry = (await db.execute(
            select(PluginCatalogEntry).where(PluginCatalogEntry.plugin_name == plugin_name)
        )).scalar_one_or_none()
        if not entry:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Catalog entry not found")

        changes = body.model_dump(exclude_none=True)
        if body.service_slug is not None and body.service_slug != "":
            svc = (await db.execute(
                select(GatewayService).where(GatewayService.slug == body.service_slug)
            )).scalar_one_or_none()
            if not svc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown service '{body.service_slug}'")
        for field_name, value in changes.items():
            setattr(entry, field_name, value)
        _audit(db, actor=admin, action="plugin_catalog.updated", target=plugin_name, metadata=changes)
        await db.commit()
        presence = await _service_key_presence(db, {entry.service_slug} if entry.service_slug else set())
        return _entry_dict(entry, has_key=presence.get(entry.service_slug, False))


@router.delete("/{plugin_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog(plugin_name: str, admin: User = Depends(require_admin)):
    async with db_session.get_session() as db:
        entry = (await db.execute(
            select(PluginCatalogEntry).where(PluginCatalogEntry.plugin_name == plugin_name)
        )).scalar_one_or_none()
        if not entry:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Catalog entry not found")
        _audit(db, actor=admin, action="plugin_catalog.deleted", target=plugin_name,
               metadata={"tier": entry.tier, "service_slug": entry.service_slug})
        await db.delete(entry)
        await db.commit()


# ── Install hook (plan 026 §Install hook, option 1: control-plane-initiated) ──

@router.post("/install")
async def install_on_agent(body: InstallRequest, request: Request, admin: User = Depends(require_admin)):
    """Install a supported plugin onto one agent and provision its key.

    Records the plugin in the agent's ``installed_plugins`` (so membership
    provisioning + discovery pick it up), best-effort installs the plugin code on
    the machine, then pushes the gateway env delta (new token + the plugin's
    service vars) via ``update_machine_env`` — restarting the machine with the
    key wired. Idempotent: re-installing is a no-op beyond a refreshed env.
    """
    from cloud.api.gateway_env_delta import apply_gateway_env_delta

    async with db_session.get_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.id == uuid.UUID(body.agent_id))
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        entry = (await db.execute(
            select(PluginCatalogEntry).where(PluginCatalogEntry.plugin_name == body.plugin_name)
        )).scalar_one_or_none()
        if not entry:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Plugin not in catalog")

        overrides = dict(agent.config_overrides or {})
        installed = list(overrides.get("installed_plugins") or [])
        if body.plugin_name not in installed:
            installed.append(body.plugin_name)
        overrides["installed_plugins"] = installed
        agent.config_overrides = overrides
        _audit(db, actor=admin, action="plugin_catalog.installed", target=body.plugin_name,
               metadata={"agent_id": body.agent_id, "service_slug": entry.service_slug})
        await db.commit()
        agent_id = agent.id
        marketplace_url = entry.marketplace_url

    result = await apply_gateway_env_delta(agent_id, marketplace_url=marketplace_url,
                                           plugin_name=body.plugin_name, admin_email=admin.email)
    return {"ok": True, "plugin_name": body.plugin_name, **result}
