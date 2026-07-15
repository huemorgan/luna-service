"""Admin API for the credential gateway — services registry, key pools, usage.

Key values are write-only: accepted on create, encrypted at rest, never
returned by any endpoint.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from cloud.auth.deps import enforce_same_origin, require_admin
from cloud.db import session as db_session
from cloud.db.models import Agent, AuditLog, GatewayKey, GatewayModel, GatewayService, UsageEvent, User
from cloud.gateway.crypto import encrypt_key
from cloud.gateway.registry import default_names, parse_auth_style
from cloud.gateway.tokens import issue_token
from cloud.provisioning.model_catalog import invalidate_catalog_cache

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/gateway", tags=["gateway-admin"],
                   dependencies=[Depends(enforce_same_origin)])


def _audit(db, *, actor: User, action: str, target: str, metadata: dict | None = None):
    db.add(AuditLog(
        actor_user_id=actor.id,
        action=action,
        target=target,
        metadata_=metadata,
    ))


# ── Schemas ───────────────────────────────────────────────────────────────────

class ServiceCreate(BaseModel):
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str
    upstream_url: str
    auth_style: str
    luna_credential_name: str | None = None
    luna_env_key_var: str | None = None
    luna_env_base_url_var: str | None = None
    enabled: bool = True
    provision_by_default: bool = False
    # Plaintext {VAR: value} of plain env vars a bound plugin needs on the machine
    # (e.g. OAuth app creds LUNA_MONDAY_CLIENT_ID/_SECRET). Encrypted at rest;
    # never returned by any endpoint (only the var names are, via extra_env_keys).
    extra_env: dict[str, str] | None = None


class ServiceUpdate(BaseModel):
    display_name: str | None = None
    upstream_url: str | None = None
    auth_style: str | None = None
    luna_credential_name: str | None = None
    enabled: bool | None = None
    provision_by_default: bool | None = None
    # Full replacement of the extra_env map (plaintext in, encrypted at rest).
    # {} clears it; None leaves it unchanged.
    extra_env: dict[str, str] | None = None


class KeyCreate(BaseModel):
    api_key: str = Field(min_length=1)
    label: str = ""
    scope: str = "global"  # "global" | "agent:<uuid>"
    priority: int = 1


class KeyUpdate(BaseModel):
    is_active: bool | None = None
    priority: int | None = None
    clear_cooldown: bool = False


def _service_dict(svc: GatewayService, key_count: int = 0) -> dict:
    return {
        "slug": svc.slug,
        "display_name": svc.display_name,
        "upstream_url": svc.upstream_url,
        "auth_style": svc.auth_style,
        "luna_credential_name": svc.luna_credential_name,
        "luna_env_key_var": svc.luna_env_key_var,
        "luna_env_base_url_var": svc.luna_env_base_url_var,
        "enabled": svc.enabled,
        "provision_by_default": svc.provision_by_default,
        # Var names only — values are write-only, never returned.
        "extra_env_keys": sorted((svc.extra_env or {}).keys()),
        "key_count": key_count,
    }


def _key_dict(key: GatewayKey) -> dict:
    now = datetime.now(timezone.utc)
    cooldown = key.cooldown_until
    if cooldown is not None and cooldown.tzinfo is None:  # SQLite test backend
        cooldown = cooldown.replace(tzinfo=timezone.utc)
    cooling = cooldown is not None and cooldown > now
    return {
        "id": str(key.id),
        "service_slug": key.service_slug,
        "scope": key.scope,
        "priority": key.priority,
        "label": key.label,
        "is_active": key.is_active,
        "on_cooldown": cooling,
        "cooldown_until": cooldown.isoformat() if cooling else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "created_at": key.created_at.isoformat() if key.created_at else None,
    }


# ── Services ──────────────────────────────────────────────────────────────────

@router.get("/services")
async def list_services(admin: User = Depends(require_admin)):
    async with db_session.get_session() as db:
        services = (await db.execute(
            select(GatewayService).order_by(GatewayService.slug)
        )).scalars().all()
        counts = dict((await db.execute(
            select(GatewayKey.service_slug, func.count())
            .group_by(GatewayKey.service_slug)
        )).all())
    return [_service_dict(s, counts.get(s.slug, 0)) for s in services]


@router.post("/services", status_code=status.HTTP_201_CREATED)
async def create_service(body: ServiceCreate, request: Request, admin: User = Depends(require_admin)):
    try:
        parse_auth_style(body.auth_style)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    async with db_session.get_session() as db:
        existing = (await db.execute(
            select(GatewayService).where(GatewayService.slug == body.slug)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Service '{body.slug}' already exists")

        names = default_names(body.slug)
        svc = GatewayService(
            slug=body.slug,
            display_name=body.display_name,
            upstream_url=body.upstream_url.rstrip("/"),
            auth_style=body.auth_style,
            luna_credential_name=body.luna_credential_name or names["luna_credential_name"],
            luna_env_key_var=body.luna_env_key_var or names["luna_env_key_var"],
            luna_env_base_url_var=body.luna_env_base_url_var or names["luna_env_base_url_var"],
            enabled=body.enabled,
            provision_by_default=body.provision_by_default,
            extra_env={k: encrypt_key(v) for k, v in (body.extra_env or {}).items()} or None,
        )
        db.add(svc)
        _audit(db, actor=admin, action="gateway.service.created", target=body.slug,
               metadata={"upstream_url": body.upstream_url})
        await db.commit()
        return _service_dict(svc)


@router.patch("/services/{slug}")
async def update_service(slug: str, body: ServiceUpdate, admin: User = Depends(require_admin)):
    if body.auth_style is not None:
        try:
            parse_auth_style(body.auth_style)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    async with db_session.get_session() as db:
        svc = (await db.execute(
            select(GatewayService).where(GatewayService.slug == slug)
        )).scalar_one_or_none()
        if not svc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found")

        changes = body.model_dump(exclude_none=True)
        # extra_env is a full-replacement map: encrypt each value, store {}→None.
        # Audit records only the var names, never the secret values.
        if "extra_env" in changes:
            plain = changes.pop("extra_env")
            svc.extra_env = {k: encrypt_key(v) for k, v in plain.items()} or None
            changes["extra_env_keys"] = sorted(plain.keys())
        for field_name, value in changes.items():
            if field_name == "extra_env_keys":
                continue
            setattr(svc, field_name, value.rstrip("/") if field_name == "upstream_url" else value)
        _audit(db, actor=admin, action="gateway.service.updated", target=slug, metadata=changes)
        await db.commit()
        return _service_dict(svc)


# ── Keys ──────────────────────────────────────────────────────────────────────

@router.get("/services/{slug}/keys")
async def list_keys(slug: str, admin: User = Depends(require_admin)):
    async with db_session.get_session() as db:
        keys = (await db.execute(
            select(GatewayKey).where(GatewayKey.service_slug == slug)
            .order_by(GatewayKey.scope, GatewayKey.priority)
        )).scalars().all()
    return [_key_dict(k) for k in keys]


@router.post("/services/{slug}/keys", status_code=status.HTTP_201_CREATED)
async def add_key(slug: str, body: KeyCreate, admin: User = Depends(require_admin)):
    if body.scope != "global" and not body.scope.startswith("agent:"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "scope must be 'global' or 'agent:<id>'")
    if body.scope.startswith("agent:"):
        try:
            uuid.UUID(body.scope.removeprefix("agent:"))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid agent id in scope")

    async with db_session.get_session() as db:
        svc = (await db.execute(
            select(GatewayService).where(GatewayService.slug == slug)
        )).scalar_one_or_none()
        if not svc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found")

        dup = (await db.execute(
            select(GatewayKey).where(
                GatewayKey.service_slug == slug,
                GatewayKey.scope == body.scope,
                GatewayKey.priority == body.priority,
            )
        )).scalar_one_or_none()
        if dup:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A key with priority {body.priority} already exists for scope '{body.scope}'",
            )

        key = GatewayKey(
            service_slug=slug,
            scope=body.scope,
            priority=body.priority,
            api_key_enc=encrypt_key(body.api_key),
            label=body.label,
        )
        db.add(key)
        # Audit records metadata only — never the key value.
        _audit(db, actor=admin, action="gateway.key.added", target=slug,
               metadata={"scope": body.scope, "priority": body.priority, "label": body.label})
        await db.commit()
        return _key_dict(key)


@router.patch("/keys/{key_id}")
async def update_key(key_id: str, body: KeyUpdate, admin: User = Depends(require_admin)):
    async with db_session.get_session() as db:
        key = (await db.execute(
            select(GatewayKey).where(GatewayKey.id == uuid.UUID(key_id))
        )).scalar_one_or_none()
        if not key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")

        if body.is_active is not None:
            key.is_active = body.is_active
        if body.priority is not None:
            key.priority = body.priority
        if body.clear_cooldown:
            key.cooldown_until = None
        _audit(db, actor=admin, action="gateway.key.updated", target=key.service_slug,
               metadata={"key_id": key_id, **body.model_dump(exclude_none=True)})
        await db.commit()
        return _key_dict(key)


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(key_id: str, admin: User = Depends(require_admin)):
    async with db_session.get_session() as db:
        key = (await db.execute(
            select(GatewayKey).where(GatewayKey.id == uuid.UUID(key_id))
        )).scalar_one_or_none()
        if not key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
        _audit(db, actor=admin, action="gateway.key.deleted", target=key.service_slug,
               metadata={"key_id": key_id, "label": key.label, "scope": key.scope})
        await db.delete(key)
        await db.commit()


# ── Tenant tokens ─────────────────────────────────────────────────────────────

@router.post("/agents/{agent_id}/token")
async def issue_agent_token(agent_id: str, admin: User = Depends(require_admin)):
    """Issue (and rotate) a tenant token. The raw value is returned ONCE."""
    async with db_session.get_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.id == uuid.UUID(agent_id))
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        raw = await issue_token(db, agent.id)
        _audit(db, actor=admin, action="gateway.token.issued", target=agent.slug,
               metadata={"agent_id": agent_id})
        await db.commit()
    return {"token": raw, "note": "Shown once. Inject as the service env key var on the machine."}


# ── Per-agent guardrail policy (plan 026.1) ───────────────────────────────────

class PolicyUpdate(BaseModel):
    allow: list[str] | None = None
    deny: list[str] | None = None
    monthly_request_cap: int | None = None


@router.get("/agents/{agent_id}/policy")
async def get_agent_policy_route(agent_id: str, admin: User = Depends(require_admin)):
    async with db_session.get_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.id == uuid.UUID(agent_id))
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        return (agent.config_overrides or {}).get("gateway") or {}


@router.put("/agents/{agent_id}/policy")
async def set_agent_policy(agent_id: str, body: PolicyUpdate, admin: User = Depends(require_admin)):
    """Set this agent's gateway allow/deny + budget. Empty fields are dropped."""
    from cloud.gateway.policy import invalidate_policy_cache

    aid = uuid.UUID(agent_id)
    async with db_session.get_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        overrides = dict(agent.config_overrides or {})
        gw: dict = {}
        if body.allow:
            gw["allow"] = body.allow
        if body.deny:
            gw["deny"] = body.deny
        if body.monthly_request_cap:
            gw["monthly_request_cap"] = body.monthly_request_cap
        if gw:
            overrides["gateway"] = gw
        else:
            overrides.pop("gateway", None)
        agent.config_overrides = overrides or None
        _audit(db, actor=admin, action="gateway.policy.updated", target=agent.slug, metadata=gw)
        await db.commit()
    invalidate_policy_cache(aid)
    return gw


# ── Usage ─────────────────────────────────────────────────────────────────────

@router.get("/usage")
async def usage_summary(
    agent_id: str | None = Query(default=None),
    service: str | None = Query(default=None),
    admin: User = Depends(require_admin),
):
    """Aggregated usage (last 30 days) grouped by agent + service + billable."""
    async with db_session.get_session() as db:
        q = (
            select(
                UsageEvent.agent_id,
                UsageEvent.service_slug,
                UsageEvent.billable,
                func.count().label("requests"),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
            )
            .group_by(UsageEvent.agent_id, UsageEvent.service_slug, UsageEvent.billable)
            .order_by(func.count().desc())
        )
        if agent_id:
            q = q.where(UsageEvent.agent_id == uuid.UUID(agent_id))
        if service:
            q = q.where(UsageEvent.service_slug == service)
        rows = (await db.execute(q)).all()

        slugs = {}
        agent_ids = [r.agent_id for r in rows if r.agent_id]
        if agent_ids:
            agents = (await db.execute(
                select(Agent.id, Agent.slug).where(Agent.id.in_(agent_ids))
            )).all()
            slugs = {a.id: a.slug for a in agents}

    return [
        {
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "agent_slug": slugs.get(r.agent_id),
            "service_slug": r.service_slug,
            "billable": r.billable,
            "requests": r.requests,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
        }
        for r in rows
    ]


@router.get("/agents-light")
async def list_agents_light(admin: User = Depends(require_admin)):
    """Minimal agent list for the key-scope picker."""
    async with db_session.get_session() as db:
        agents = (await db.execute(
            select(Agent.id, Agent.slug, Agent.name).order_by(Agent.created_at.desc())
        )).all()
    return [{"id": str(a.id), "slug": a.slug, "name": a.name} for a in agents]


# ── Models catalog (Plan 018) ──────────────────────────────────────────────────

_VALID_KINDS = {"reasoning", "summarization", "embedding", "image"}


class ModelCreate(BaseModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    label: str | None = None
    context_window: int | None = None
    kinds: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    tier: str | None = None
    input_cost: float | None = None
    output_cost: float | None = None
    recommended_default: bool = False
    deprecated: bool = False
    enabled: bool = True


class ModelUpdate(BaseModel):
    label: str | None = None
    context_window: int | None = None
    kinds: list[str] | None = None
    aliases: list[str] | None = None
    tier: str | None = None
    input_cost: float | None = None
    output_cost: float | None = None
    recommended_default: bool | None = None
    deprecated: bool | None = None
    enabled: bool | None = None


def _model_dict(m: GatewayModel, key_count: int = 0) -> dict:
    return {
        "id": str(m.id),
        "provider": m.provider,
        "model": m.model,
        "label": m.label,
        "context_window": m.context_window,
        "kinds": list(m.kinds or []),
        "aliases": list(m.aliases or []),
        "tier": m.tier,
        "input_cost": m.input_cost,
        "output_cost": m.output_cost,
        "recommended_default": m.recommended_default,
        "deprecated": m.deprecated,
        "enabled": m.enabled,
        "key_count": key_count,
    }


def _validate_kinds(kinds: list[str]) -> None:
    bad = [k for k in kinds if k not in _VALID_KINDS]
    if bad:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Invalid kind(s): {bad}. Allowed: {sorted(_VALID_KINDS)}",
        )


async def _clear_recommended_for_kinds(db, kinds: list[str], *, except_id: uuid.UUID) -> None:
    """Keep at most one recommended_default per kind family: when a model is made
    the default, drop the flag from every other model sharing any of its kinds."""
    others = (await db.execute(
        select(GatewayModel).where(
            GatewayModel.recommended_default.is_(True),
            GatewayModel.id != except_id,
        )
    )).scalars().all()
    for other in others:
        if set(other.kinds or []) & set(kinds):
            other.recommended_default = False


@router.get("/models")
async def list_models(admin: User = Depends(require_admin)):
    """All catalog models (in + out) with the provider's key count attached."""
    async with db_session.get_session() as db:
        models = (await db.execute(
            select(GatewayModel).order_by(GatewayModel.provider, GatewayModel.model)
        )).scalars().all()
        counts = dict((await db.execute(
            select(GatewayKey.service_slug, func.count()).group_by(GatewayKey.service_slug)
        )).all())
    return [_model_dict(m, counts.get(m.provider, 0)) for m in models]


@router.post("/models", status_code=status.HTTP_201_CREATED)
async def create_model(body: ModelCreate, admin: User = Depends(require_admin)):
    _validate_kinds(body.kinds)
    async with db_session.get_session() as db:
        existing = (await db.execute(
            select(GatewayModel).where(
                GatewayModel.provider == body.provider, GatewayModel.model == body.model,
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Model '{body.provider}:{body.model}' already exists",
            )
        m = GatewayModel(**body.model_dump())
        db.add(m)
        await db.flush()
        if body.recommended_default and body.kinds:
            await _clear_recommended_for_kinds(db, body.kinds, except_id=m.id)
        _audit(db, actor=admin, action="gateway.model.created", target=f"{body.provider}:{body.model}",
               metadata={"kinds": body.kinds, "enabled": body.enabled})
        await db.commit()
        result = _model_dict(m)
    invalidate_catalog_cache()
    return result


@router.patch("/models/{model_id}")
async def update_model(model_id: str, body: ModelUpdate, admin: User = Depends(require_admin)):
    if body.kinds is not None:
        _validate_kinds(body.kinds)
    async with db_session.get_session() as db:
        m = (await db.execute(
            select(GatewayModel).where(GatewayModel.id == uuid.UUID(model_id))
        )).scalar_one_or_none()
        if not m:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")

        changes = body.model_dump(exclude_none=True)
        for field_name, value in changes.items():
            setattr(m, field_name, value)
        # If this model just became the default, clear the flag from peers of the
        # same kind so there's exactly one default per purpose.
        if body.recommended_default:
            await _clear_recommended_for_kinds(db, list(m.kinds or []), except_id=m.id)
        _audit(db, actor=admin, action="gateway.model.updated",
               target=f"{m.provider}:{m.model}", metadata=changes)
        await db.commit()
        result = _model_dict(m)
    invalidate_catalog_cache()
    return result


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: str, admin: User = Depends(require_admin)):
    async with db_session.get_session() as db:
        m = (await db.execute(
            select(GatewayModel).where(GatewayModel.id == uuid.UUID(model_id))
        )).scalar_one_or_none()
        if not m:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")
        _audit(db, actor=admin, action="gateway.model.deleted", target=f"{m.provider}:{m.model}",
               metadata={"kinds": list(m.kinds or [])})
        await db.delete(m)
        await db.commit()
    invalidate_catalog_cache()
