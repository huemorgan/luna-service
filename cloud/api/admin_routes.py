"""Admin routes — manage admins, Luna images, and Fly machines."""

from __future__ import annotations

import base64
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.auth.deps import require_admin
from cloud.config import get_settings
from cloud.db.models import Agent, AuditLog, LunaImage, User
from cloud.db.session import get_session as get_db_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Audit helpers ─────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For (Render sets this) or fall back."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _audit(
    db: AsyncSession,
    *,
    action: str,
    actor: User | None = None,
    actor_ip: str | None = None,
    target: str | None = None,
    account_id: uuid.UUID | None = None,
    metadata: dict | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> None:
    db.add(AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_ip=actor_ip,
        action=action,
        target=target,
        account_id=account_id,
        metadata_=metadata,
        before_state=before_state,
        after_state=after_state,
    ))


# ── Schemas ──────────────────────────────────────────────────────────────────

class AddAdminRequest(BaseModel):
    email: str


class SetMainImageRequest(BaseModel):
    pass


class BuildImageRequest(BaseModel):
    pass


class BuildWebhookPayload(BaseModel):
    image_id: str
    status: str  # "built" | "failed"
    git_sha: str | None = None
    error: str | None = None
    build_run_id: str | None = None


# ── Admins ───────────────────────────────────────────────────────────────────

@router.get("/admins")
async def list_admins(admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        admins = (await db.execute(
            select(User).where(User.is_admin == True).order_by(User.email)  # noqa: E712
        )).scalars().all()
    return [
        {"id": str(u.id), "email": u.email, "name": u.name, "avatar_url": u.avatar_url}
        for u in admins
    ]


@router.get("/users")
async def list_users(admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        users = (await db.execute(
            select(User).order_by(User.email)
        )).scalars().all()
    return [
        {"id": str(u.id), "email": u.email, "name": u.name, "is_admin": u.is_admin}
        for u in users
    ]


@router.post("/admins")
async def add_admin(body: AddAdminRequest, request: Request, admin: User = Depends(require_admin)):
    ip = _client_ip(request)
    async with get_db_session() as db:
        user = (await db.execute(
            select(User).where(User.email == body.email.strip().lower())
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        if user.is_admin:
            return {"id": str(user.id), "email": user.email, "name": user.name, "already": True}

        user.is_admin = True
        await _audit(db, action="admin.added", actor=admin, actor_ip=ip,
                     target=str(user.id), metadata={"email": user.email},
                     before_state={"is_admin": False}, after_state={"is_admin": True})
        await db.commit()
    return {"id": str(user.id), "email": user.email, "name": user.name}


@router.delete("/admins/{user_id}")
async def remove_admin(user_id: str, request: Request, admin: User = Depends(require_admin)):
    ip = _client_ip(request)
    async with get_db_session() as db:
        target = (await db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )).scalar_one_or_none()
        if not target:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

        if target.id == admin.id:
            admin_count = (await db.execute(
                select(func.count()).select_from(User).where(User.is_admin == True)  # noqa: E712
            )).scalar()
            if admin_count <= 1:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot remove the last admin")

        target.is_admin = False
        await _audit(db, action="admin.removed", actor=admin, actor_ip=ip,
                     target=str(target.id), metadata={"email": target.email},
                     before_state={"is_admin": True}, after_state={"is_admin": False})
        await db.commit()
    return {"ok": True}


# ── Luna Images ──────────────────────────────────────────────────────────────

_github_version_cache: dict[str, tuple[float, str | None]] = {}
GITHUB_CACHE_TTL = 300  # 5 minutes

LUNA_GITHUB_REPO = "huemorgan/luna"
LUNA_VERSION_PATH = "luna/__init__.py"


async def _fetch_luna_version_from_github() -> tuple[str | None, str]:
    """Fetch __version__ from the luna repo's main branch via GitHub API.

    Returns (version, source) where source is "github" or "disk".
    Caches for 5 minutes. Falls back to disk if the API call fails.
    """
    cache_key = "luna_version"
    now = time.monotonic()
    cached = _github_version_cache.get(cache_key)
    if cached and now - cached[0] < GITHUB_CACHE_TTL:
        return cached[1]

    try:
        api_headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
        gh_token = os.environ.get("CLOUD_GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
        if gh_token:
            api_headers["Authorization"] = f"Bearer {gh_token}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{LUNA_GITHUB_REPO}/contents/{LUNA_VERSION_PATH}",
                params={"ref": "main"},
                headers=api_headers,
            )
        if resp.status_code == 200:
            content_b64 = resp.json().get("content", "")
            content = base64.b64decode(content_b64).decode("utf-8")
            m = re.search(r'__version__\s*=\s*"(.+?)"', content)
            version = m.group(1) if m else None
            result = (version, "github")
            _github_version_cache[cache_key] = (now, result)
            return result
        log.warning("GitHub API returned %s for luna version check", resp.status_code)
    except Exception as exc:
        log.warning("GitHub API call failed: %s", exc)

    result = (_read_luna_version_from_disk(), "disk")
    _github_version_cache[cache_key] = (now, result)
    return result


def _read_luna_version_from_disk() -> str | None:
    """Fallback: read from cloud/.luna-version or submodule on disk."""
    version_file = Path(__file__).resolve().parents[1] / ".luna-version"
    if version_file.exists():
        v = version_file.read_text().strip()
        if v:
            return v
    init_path = Path(__file__).resolve().parents[2] / "luna" / "luna" / "__init__.py"
    if not init_path.exists():
        return None
    content = init_path.read_text()
    m = re.search(r'__version__\s*=\s*"(.+?)"', content)
    return m.group(1) if m else None


PLUGIN_META = [
    {"key": "plugin_vault", "name": "Vault", "description": "Encrypted credential storage", "required": True},
    {"key": "plugin_memory", "name": "Memory", "description": "Long-term semantic recall", "required": True},
    {"key": "plugin_identity", "name": "Identity", "description": "Agent name, persona, settings", "required": True},
    {"key": "plugin_mcp", "name": "MCP", "description": "External tool connections", "required": False},
    {"key": "plugin_web_access", "name": "Web Access", "description": "Web search, fetch, HTTP", "required": False},
    {"key": "plugin_funnelfighters", "name": "FunnelFighters", "description": "Marketing intelligence", "required": False},
    {"key": "plugin_brain", "name": "Brain", "description": "Live neural activity visualization", "required": False},
    {"key": "plugin_files", "name": "Files", "description": "File storage and browser", "required": False},
    {"key": "plugin_meta", "name": "Meta", "description": "Toggle other plugins at runtime", "required": True},
    {"key": "plugin_approvals", "name": "Approvals", "description": "Gates risky actions for owner consent", "required": True},
    {"key": "plugin_web", "name": "Web Server", "description": "Core HTTP server and auth", "required": True},
]

DEFAULT_IMAGE_CONFIG = {
    "machine": {
        "cpu_kind": "shared",
        "cpus": 1,
        "memory_mb": 1024,
        "region": "sjc",
    },
    "models": {
        "primary": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
        "fast": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
    },
    "plugins": {
        "plugin_vault": True,
        "plugin_memory": True,
        "plugin_identity": True,
        "plugin_mcp": True,
        "plugin_web_access": True,
        "plugin_funnelfighters": True,
        "plugin_brain": True,
        "plugin_files": True,
        "plugin_meta": True,
        "plugin_approvals": True,
        "plugin_web": True,
    },
    "env": {},
    # Plan 016: per-service defaults (resolver in cloud/provisioning/services_config.py).
    "services": {
        "composio": {"accounts_mode": "both"},
    },
}


def _image_dict(img: LunaImage, agent_count: int = 0) -> dict:
    return {
        "id": str(img.id),
        "version": img.version,
        "registry_tag": img.registry_tag,
        "is_main": img.is_main,
        "build_status": img.build_status,
        "build_run_id": img.build_run_id,
        "build_error": img.build_error,
        "git_sha": img.git_sha,
        "created_at": img.created_at.isoformat() if img.created_at else None,
        "built_at": img.built_at.isoformat() if img.built_at else None,
        "agent_count": agent_count,
        "image_config": {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {})},
        "cache_warmed_at": img.cache_warmed_at.isoformat() if img.cache_warmed_at else None,
    }


@router.get("/images")
async def list_images(admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        images = (await db.execute(
            select(LunaImage).order_by(LunaImage.created_at.desc())
        )).scalars().all()

        counts: dict[str, int] = {}
        if images:
            rows = (await db.execute(
                select(Agent.image_version, func.count())
                .where(Agent.image_version.isnot(None))
                .group_by(Agent.image_version)
            )).all()
            counts = {r[0]: r[1] for r in rows}

    return [_image_dict(img, counts.get(img.version, 0)) for img in images]


@router.get("/images/check-update")
async def check_update(admin: User = Depends(require_admin)):
    submodule_version, source = await _fetch_luna_version_from_github()
    async with get_db_session() as db:
        latest_image = (await db.execute(
            select(LunaImage).order_by(LunaImage.created_at.desc()).limit(1)
        )).scalar_one_or_none()

    latest_built = latest_image.version if latest_image else None
    return {
        "submodule_version": submodule_version,
        "latest_built": latest_built,
        "update_available": submodule_version is not None and submodule_version != latest_built,
        "source": source,
    }


@router.get("/images/{image_id}")
async def get_image(image_id: str, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")

        agent_count = (await db.execute(
            select(func.count()).select_from(Agent).where(Agent.image_version == img.version)
        )).scalar()

    return _image_dict(img, agent_count or 0)


@router.get("/images/{image_id}/config")
async def get_image_config(image_id: str, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    return {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {})}


class ImageConfigUpdate(BaseModel):
    machine: dict | None = None
    models: dict | None = None
    plugins: dict | None = None
    env: dict | None = None
    services: dict | None = None


@router.put("/images/{image_id}/config")
async def update_image_config(
    image_id: str, body: ImageConfigUpdate, request: Request, admin: User = Depends(require_admin),
):
    ip = _client_ip(request)
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")

        before = {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {})}
        patch = body.model_dump(exclude_none=True)
        current = {**before}
        for key, val in patch.items():
            if isinstance(val, dict) and isinstance(current.get(key), dict):
                current[key] = {**current[key], **val}
            else:
                current[key] = val

        img.image_config = current
        await _audit(db, action="image.config_updated", actor=admin, actor_ip=ip,
                     target=str(img.id), metadata={"version": img.version, "patch": patch},
                     before_state=before, after_state=current)
        await db.commit()
    return current


@router.get("/plugin-meta")
async def get_plugin_meta(admin: User = Depends(require_admin)):
    return PLUGIN_META


@router.delete("/images/{image_id}")
async def delete_image(image_id: str, request: Request, admin: User = Depends(require_admin)):
    ip = _client_ip(request)
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
        if img.is_main:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete the main image")
        before = {"version": img.version, "registry_tag": img.registry_tag, "build_status": img.build_status}
        await db.delete(img)
        await _audit(db, action="image.deleted", actor=admin, actor_ip=ip,
                     target=str(img.id), metadata={"version": img.version},
                     before_state=before)
        await db.commit()
    return {"ok": True}


@router.post("/images/{image_id}/set-main")
async def set_main_image(image_id: str, request: Request, admin: User = Depends(require_admin)):
    ip = _client_ip(request)
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
        if img.build_status != "built":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only built images can be set as main")

        prev_main = (await db.execute(
            select(LunaImage).where(LunaImage.is_main == True)  # noqa: E712
        )).scalar_one_or_none()
        prev_info = {"version": prev_main.version, "id": str(prev_main.id)} if prev_main else None

        await db.execute(
            LunaImage.__table__.update().values(is_main=False)
        )
        img.is_main = True
        await _audit(db, action="image.promoted_to_main", actor=admin, actor_ip=ip,
                     target=str(img.id), metadata={"version": img.version},
                     before_state={"previous_main": prev_info},
                     after_state={"new_main": {"version": img.version, "id": str(img.id)}})
        await db.commit()
        registry_tag = img.registry_tag
        image_config = {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {})}

    import asyncio
    asyncio.create_task(_warm_image_background(image_id, registry_tag, image_config))

    return {"ok": True, "version": img.version}


async def _warm_image_background(image_id: str, registry_tag: str, image_config: dict) -> None:
    """Background task: warm the image cache and update the DB timestamp."""
    try:
        if not os.environ.get("FLY_API_TOKEN"):
            return
        from cloud.runtime.fly_machines import FlyMachinesRuntime
        fly = FlyMachinesRuntime()
        region = image_config.get("machine", {}).get("region", os.environ.get("FLY_REGION", "sjc"))
        await fly.warm_image_cache(registry_tag, region=region)

        async with get_db_session() as db:
            img = (await db.execute(
                select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
            )).scalar_one()
            img.cache_warmed_at = datetime.now(timezone.utc)
            await _audit(db, action="image.cache_warmed",
                         target=image_id, metadata={"version": img.version, "region": region})
            await db.commit()
        log.info("Image cache warmed for %s in %s", registry_tag, region)
    except Exception as e:
        log.error("Image cache warming failed for %s: %s", registry_tag, e)


@router.post("/images/{image_id}/warm-cache")
async def warm_image_cache(image_id: str, request: Request, admin: User = Depends(require_admin)):
    """Manually trigger image cache warming."""
    ip = _client_ip(request)
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
        if img.build_status != "built":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only built images can be warmed")
        registry_tag = img.registry_tag
        image_config = {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {})}

    if not os.environ.get("FLY_API_TOKEN"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Fly API not configured")

    from cloud.runtime.fly_machines import FlyMachinesRuntime
    fly = FlyMachinesRuntime()
    region = image_config.get("machine", {}).get("region", os.environ.get("FLY_REGION", "sjc"))
    try:
        await fly.warm_image_cache(registry_tag, region=region)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Cache warming failed: {e}")

    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one()
        img.cache_warmed_at = datetime.now(timezone.utc)
        await _audit(db, action="image.cache_warmed", actor=admin, actor_ip=ip,
                     target=str(img.id), metadata={"version": img.version, "region": region})
        await db.commit()

    return {"ok": True, "region": region, "cache_warmed_at": img.cache_warmed_at.isoformat()}


@router.post("/images/build")
async def build_image(request: Request, admin: User = Depends(require_admin), version: str | None = None):
    ip = _client_ip(request)
    settings = get_settings()
    if not version:
        version_result = await _fetch_luna_version_from_github()
        version = version_result[0]
    if not version:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot determine Luna version")

    fly_app = os.environ.get("FLY_APP", "luna-agents")
    registry_tag = f"registry.fly.io/{fly_app}:{version}"

    async with get_db_session() as db:
        existing = (await db.execute(
            select(LunaImage).where(LunaImage.version == version)
        )).scalar_one_or_none()
        if existing and existing.build_status in ("built", "building"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Image {version} already exists (status: {existing.build_status})",
            )

        img = LunaImage(
            version=version,
            registry_tag=registry_tag,
            build_status="building",
            created_by=admin.id,
        )
        if existing:
            await db.delete(existing)
            await db.flush()
        db.add(img)
        await db.commit()
        await db.refresh(img)
        image_id = str(img.id)

        await _audit(db, action="image.build_triggered", actor=admin, actor_ip=ip,
                     target=image_id, metadata={"version": version, "registry_tag": registry_tag},
                     after_state={"version": version, "build_status": "building"})
        await db.commit()

    if settings.github_pat:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.github.com/repos/{settings.github_repo}/actions/workflows/build-luna-image.yml/dispatches",
                    headers={
                        "Authorization": f"Bearer {settings.github_pat}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                    json={
                        "ref": "main",
                        "inputs": {"version": version, "image_id": image_id},
                    },
                    timeout=15,
                )
                resp.raise_for_status()
        except Exception as e:
            log.error("Failed to trigger GitHub Actions build: %s", e)
            async with get_db_session() as db:
                img = (await db.execute(
                    select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
                )).scalar_one()
                img.build_status = "failed"
                img.build_error = f"Failed to trigger build: {e}"
                await db.commit()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to trigger build: {e}")
    else:
        log.warning("CLOUD_GITHUB_PAT not set — image record created but no build triggered")

    return _image_dict(img)


# ── Build webhook (called by GitHub Actions) ─────────────────────────────────

@router.post("/webhooks/build-complete")
async def build_complete(
    body: BuildWebhookPayload,
    request: Request,
    authorization: str = Header(...),
):
    ip = _client_ip(request)
    settings = get_settings()
    expected = f"Bearer {settings.admin_webhook_secret}"
    if authorization != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook secret")

    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(body.image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")

        before = {"build_status": img.build_status}
        img.build_status = body.status
        img.git_sha = body.git_sha
        if body.build_run_id:
            img.build_run_id = body.build_run_id
        if body.status == "built":
            img.built_at = datetime.now(timezone.utc)
        if body.error:
            img.build_error = body.error

        action = "image.build_completed" if body.status == "built" else "image.build_failed"
        await _audit(db, action=action, actor_ip=ip,
                     target=str(img.id),
                     metadata={"version": img.version, "git_sha": body.git_sha,
                               "build_run_id": body.build_run_id, "error": body.error,
                               "actor_type": "system"},
                     before_state=before,
                     after_state={"build_status": body.status})
        await db.commit()

    return {"ok": True}


# ── Machines ─────────────────────────────────────────────────────────────────

@router.get("/machines")
async def list_machines(admin: User = Depends(require_admin)):
    from cloud.provisioning.services_config import (
        hosted_composio_key_provisioned,
        resolve_composio_accounts_mode,
        resolve_models,
    )

    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.runtime_ref.isnot(None)).order_by(Agent.created_at)
        )).scalars().all()

        # Build a version → image_config map so the per-row resolver has the image default.
        versions = {a.image_version for a in agents if a.image_version}
        images = (await db.execute(
            select(LunaImage).where(LunaImage.version.in_(versions))
        )).scalars().all() if versions else []
        image_config_by_version = {
            img.version: {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {})}
            for img in images
        }
        hosted_provisioned = await hosted_composio_key_provisioned(db)

    fly_machines: list[dict] = []
    if os.environ.get("FLY_API_TOKEN"):
        try:
            from cloud.runtime.fly_machines import FlyMachinesRuntime
            fly = FlyMachinesRuntime()
            fly_machines = await fly.list_machines()
        except Exception as e:
            log.warning("Failed to list Fly machines: %s", e)

    machines_by_id = {m.get("id"): m for m in fly_machines}

    result = []
    for agent in agents:
        fly_info = machines_by_id.get(agent.runtime_ref, {})
        config = fly_info.get("config") or {}
        image_cfg = image_config_by_version.get(agent.image_version or "")
        override = (agent.config_overrides or {}).get("services", {}).get("composio", {}).get("accounts_mode")
        resolved = resolve_composio_accounts_mode(
            image_cfg, agent.config_overrides, hosted_key_provisioned=hosted_provisioned,
        )

        # Plan 017.1: resolved + per-role model override.
        models_resolved = resolve_models(image_cfg, agent.config_overrides)
        models_override_raw = (agent.config_overrides or {}).get("models") or {}
        primary_override = models_override_raw.get("primary") if isinstance(models_override_raw.get("primary"), dict) else None
        fast_override = models_override_raw.get("fast") if isinstance(models_override_raw.get("fast"), dict) else None

        result.append({
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "agent_slug": agent.slug,
            "agent_status": agent.status,
            "machine_id": agent.runtime_ref,
            "runtime_kind": agent.runtime_kind,
            "image_version": agent.image_version,
            "fly_state": fly_info.get("state"),
            "fly_region": fly_info.get("region"),
            "fly_image": config.get("image"),
            "fly_created_at": fly_info.get("created_at"),
            "composio_accounts_mode": resolved,
            "composio_accounts_mode_override": override,
            "primary_model": models_resolved["primary"],
            "fast_model": models_resolved["fast"],
            "primary_model_override": primary_override,
            "fast_model_override": fast_override,
        })
    return result


class MachineServicesConfigPatch(BaseModel):
    # Plan 016: when accounts_mode is None we CLEAR the override and revert to
    # the image default; otherwise set it to the provided value.
    accounts_mode: str | None = None


@router.patch("/machines/{machine_id}/services/composio")
async def patch_machine_composio_config(
    machine_id: str,
    body: MachineServicesConfigPatch,
    request: Request,
    admin: User = Depends(require_admin),
):
    """Set or clear the per-agent Composio accounts-mode override, then push
    LUNA_CONNECTORS_ACCOUNTS_MODE to the live machine (no full re-provision)."""
    from cloud.provisioning.services_config import (
        hosted_composio_key_provisioned,
        resolve_composio_accounts_mode,
    )

    if body.accounts_mode is not None and body.accounts_mode not in ("hosted", "user", "both"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "accounts_mode must be one of hosted/user/both or null")

    ip = _client_ip(request)
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.runtime_ref == machine_id)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No agent found for this machine")

        before = agent.config_overrides
        overrides = dict(agent.config_overrides or {})
        services = dict(overrides.get("services") or {})
        composio = dict(services.get("composio") or {})

        if body.accounts_mode is None:
            composio.pop("accounts_mode", None)
        else:
            composio["accounts_mode"] = body.accounts_mode

        if composio:
            services["composio"] = composio
        else:
            services.pop("composio", None)

        if services:
            overrides["services"] = services
        else:
            overrides.pop("services", None)

        agent.config_overrides = overrides or None

        img = (await db.execute(
            select(LunaImage).where(LunaImage.version == (agent.image_version or ""))
        )).scalar_one_or_none()
        image_cfg = {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {} if img else {})}
        hosted_provisioned = await hosted_composio_key_provisioned(db)
        resolved = resolve_composio_accounts_mode(
            image_cfg, agent.config_overrides, hosted_key_provisioned=hosted_provisioned,
        )

        await _audit(db, action="machine.services_config_updated", actor=admin, actor_ip=ip,
                     target=machine_id,
                     metadata={"service": "composio", "agent": agent.slug, "resolved": resolved},
                     before_state={"config_overrides": before},
                     after_state={"config_overrides": agent.config_overrides, "resolved_accounts_mode": resolved})
        await db.commit()

    if os.environ.get("FLY_API_TOKEN") and agent.runtime_kind in ("fly", "fly-machines"):
        from cloud.runtime.fly_machines import FlyMachinesRuntime
        fly = FlyMachinesRuntime()
        try:
            await fly.update_machine_env(
                machine_id, {"LUNA_CONNECTORS_ACCOUNTS_MODE": resolved},
            )
        except Exception as e:
            log.error("Failed to push connectors mode to machine %s: %s", machine_id, e)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                f"Saved override but failed to push env: {e}")

    return {
        "ok": True,
        "config_overrides": agent.config_overrides,
        "resolved_accounts_mode": resolved,
    }


class ModelEntry(BaseModel):
    provider: str
    model: str


class MachineModelsPatch(BaseModel):
    # Plan 017.1 — null clears the override for that role, missing means
    # "don't change". Use _sentinel via Field if both keys are sent literally.
    primary: ModelEntry | None = None
    fast: ModelEntry | None = None
    clear_primary: bool = False
    clear_fast: bool = False


@router.patch("/machines/{machine_id}/models")
async def patch_machine_models(
    machine_id: str,
    body: MachineModelsPatch,
    request: Request,
    admin: User = Depends(require_admin),
):
    """Set / clear per-agent primary or fast model override and push the
    LUNA_PRIMARY_MODEL / LUNA_FAST_MODEL env vars to the live machine."""
    from cloud.provisioning.services_config import resolve_models

    ip = _client_ip(request)
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.runtime_ref == machine_id)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No agent found for this machine")

        before = agent.config_overrides
        overrides = dict(agent.config_overrides or {})
        models_o = dict(overrides.get("models") or {})

        if body.clear_primary:
            models_o.pop("primary", None)
        elif body.primary is not None:
            models_o["primary"] = body.primary.model_dump()

        if body.clear_fast:
            models_o.pop("fast", None)
        elif body.fast is not None:
            models_o["fast"] = body.fast.model_dump()

        if models_o:
            overrides["models"] = models_o
        else:
            overrides.pop("models", None)

        agent.config_overrides = overrides or None

        img = (await db.execute(
            select(LunaImage).where(LunaImage.version == (agent.image_version or ""))
        )).scalar_one_or_none()
        image_cfg = {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {} if img else {})}
        resolved = resolve_models(image_cfg, agent.config_overrides)

        await _audit(db, action="machine.models_updated", actor=admin, actor_ip=ip,
                     target=machine_id,
                     metadata={"agent": agent.slug, "resolved": resolved},
                     before_state={"config_overrides": before},
                     after_state={"config_overrides": agent.config_overrides, "resolved_models": resolved})
        await db.commit()

    if os.environ.get("FLY_API_TOKEN") and agent.runtime_kind in ("fly", "fly-machines"):
        from cloud.runtime.fly_machines import FlyMachinesRuntime
        fly = FlyMachinesRuntime()
        env_updates = {
            "LUNA_PRIMARY_MODEL": f"{resolved['primary']['provider']}:{resolved['primary']['model']}",
            "LUNA_FAST_MODEL": f"{resolved['fast']['provider']}:{resolved['fast']['model']}",
        }
        try:
            await fly.update_machine_env(machine_id, env_updates)
        except Exception as e:
            log.error("Failed to push models to machine %s: %s", machine_id, e)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                f"Saved override but failed to push env: {e}")

    return {
        "ok": True,
        "config_overrides": agent.config_overrides,
        "resolved_models": resolved,
    }


@router.post("/machines/{machine_id}/update-image")
async def update_machine_image(machine_id: str, request: Request, admin: User = Depends(require_admin)):
    """Update a single machine to the current main image."""
    ip = _client_ip(request)
    async with get_db_session() as db:
        main_image = (await db.execute(
            select(LunaImage).where(LunaImage.is_main == True, LunaImage.build_status == "built")  # noqa: E712
        )).scalar_one_or_none()
        if not main_image:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No main image set")

        agent = (await db.execute(
            select(Agent).where(Agent.runtime_ref == machine_id)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No agent found for this machine")
        old_version = agent.image_version

    if not os.environ.get("FLY_API_TOKEN"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Fly API not configured")

    from cloud.runtime.fly_machines import FlyMachinesRuntime
    fly = FlyMachinesRuntime()
    try:
        await fly.update_machine_image(machine_id, main_image.registry_tag)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to update machine: {e}")

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.runtime_ref == machine_id)
        )).scalar_one()
        agent.image_version = main_image.version
        await _audit(db, action="machine.image_updated", actor=admin, actor_ip=ip,
                     target=machine_id, metadata={"version": main_image.version, "agent": agent.slug},
                     before_state={"version": old_version},
                     after_state={"version": main_image.version})
        await db.commit()

    return {"ok": True, "version": main_image.version}


@router.post("/machines/migrate-all")
async def migrate_all_machines(request: Request, admin: User = Depends(require_admin)):
    """Update all machines to the current main image."""
    ip = _client_ip(request)
    async with get_db_session() as db:
        main_image = (await db.execute(
            select(LunaImage).where(LunaImage.is_main == True, LunaImage.build_status == "built")  # noqa: E712
        )).scalar_one_or_none()
        if not main_image:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No main image set")

        agents = (await db.execute(
            select(Agent).where(
                Agent.runtime_ref.isnot(None),
                Agent.image_version != main_image.version,
            )
        )).scalars().all()

    if not agents:
        return {"ok": True, "updated": 0, "version": main_image.version}

    if not os.environ.get("FLY_API_TOKEN"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Fly API not configured")

    from cloud.runtime.fly_machines import FlyMachinesRuntime
    fly = FlyMachinesRuntime()

    before_versions = {a.slug: a.image_version for a in agents}
    updated = 0
    errors = []
    for agent in agents:
        try:
            await fly.update_machine_image(agent.runtime_ref, main_image.registry_tag)
            async with get_db_session() as db:
                a = (await db.execute(
                    select(Agent).where(Agent.id == agent.id)
                )).scalar_one()
                a.image_version = main_image.version
                await db.commit()
            updated += 1
        except Exception as e:
            log.error("Failed to update machine %s: %s", agent.runtime_ref, e)
            errors.append({"machine_id": agent.runtime_ref, "agent": agent.slug, "error": str(e)})

    async with get_db_session() as db:
        await _audit(db, action="machine.migrate_all", actor=admin, actor_ip=ip,
                     metadata={"version": main_image.version, "updated": updated, "errors": len(errors)},
                     before_state={"agent_versions": before_versions},
                     after_state={"version": main_image.version, "updated_count": updated})
        await db.commit()

    return {"ok": True, "updated": updated, "errors": errors, "version": main_image.version}


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit-log")
async def list_audit_log(
    admin: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    action: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    target: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    q: Optional[str] = Query(None),
):
    async with get_db_session() as db:
        query = select(AuditLog).order_by(AuditLog.created_at.desc())
        count_query = select(func.count()).select_from(AuditLog)

        if action:
            query = query.where(AuditLog.action.startswith(action))
            count_query = count_query.where(AuditLog.action.startswith(action))
        if actor_id:
            uid = uuid.UUID(actor_id)
            query = query.where(AuditLog.actor_user_id == uid)
            count_query = count_query.where(AuditLog.actor_user_id == uid)
        if target:
            query = query.where(AuditLog.target == target)
            count_query = count_query.where(AuditLog.target == target)
        if from_date:
            from_dt = datetime.fromisoformat(from_date)
            query = query.where(AuditLog.created_at >= from_dt)
            count_query = count_query.where(AuditLog.created_at >= from_dt)
        if to_date:
            to_dt = datetime.fromisoformat(to_date)
            query = query.where(AuditLog.created_at <= to_dt)
            count_query = count_query.where(AuditLog.created_at <= to_dt)
        if q:
            from sqlalchemy import cast, String
            pattern = f"%{q}%"
            query = query.where(
                AuditLog.action.ilike(pattern) | cast(AuditLog.metadata_, String).ilike(pattern)
            )
            count_query = count_query.where(
                AuditLog.action.ilike(pattern) | cast(AuditLog.metadata_, String).ilike(pattern)
            )

        total = (await db.execute(count_query)).scalar() or 0

        offset = (page - 1) * per_page
        rows = (await db.execute(query.offset(offset).limit(per_page))).scalars().all()

        actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
        actors_by_id: dict[uuid.UUID, User] = {}
        if actor_ids:
            actors = (await db.execute(
                select(User).where(User.id.in_(actor_ids))
            )).scalars().all()
            actors_by_id = {a.id: a for a in actors}

    items = []
    for row in rows:
        actor_user = actors_by_id.get(row.actor_user_id) if row.actor_user_id else None
        items.append({
            "id": str(row.id),
            "action": row.action,
            "actor": {
                "id": str(actor_user.id),
                "name": actor_user.name,
                "email": actor_user.email,
                "avatar_url": actor_user.avatar_url,
            } if actor_user else None,
            "actor_ip": row.actor_ip,
            "target": row.target,
            "metadata": row.metadata_,
            "before_state": row.before_state,
            "after_state": row.after_state,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "per_page": per_page}


# ── Test agent from specific image ───────────────────────────────────────────


class TestAgentRequest(BaseModel):
    name: str = "Test Agent"


@router.post("/images/{image_id}/test-agent", status_code=201)
async def create_test_agent(
    image_id: str,
    request: Request,
    body: TestAgentRequest = TestAgentRequest(),
    admin: User = Depends(require_admin),
):
    """Provision a new agent on the admin's account using a specific image (not necessarily main)."""
    async with get_db_session() as db:
        image = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not image:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
        if image.build_status != "built":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Image is not built")

        from cloud.db.models import Account, Membership
        membership = (await db.execute(
            select(Membership).where(
                Membership.user_id == admin.id,
                Membership.status == "active",
            )
        )).scalar_one_or_none()
        if not membership:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admin has no active account")

        account = (await db.execute(
            select(Account).where(Account.id == membership.account_id)
        )).scalar_one()

        name = body.name.strip() or f"Test {image.version}"
        base_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "test"
        slug = f"{account.slug}-{base_slug}"
        suffix = 1
        while (await db.execute(select(Agent).where(Agent.slug == slug))).scalar_one_or_none():
            suffix += 1
            slug = f"{account.slug}-{base_slug}-{suffix}"

        agent = Agent(
            account_id=account.id,
            creator_id=admin.id,
            name=name,
            slug=slug,
            status="provisioning",
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        agent_id = str(agent.id)

        await _audit(db, action="agent.test_created", actor=admin, actor_ip=_client_ip(request),
                     target=agent_id, metadata={"image_id": image_id, "version": image.version, "agent_slug": slug},
                     after_state={"agent_id": agent_id, "slug": slug, "image_version": image.version})
        await db.commit()

    from cloud.provisioning.workflow import provision_luna_for_account_with_image
    import asyncio
    asyncio.create_task(provision_luna_for_account_with_image(
        str(account.id), agent_id=agent_id, image_id=image_id,
    ))

    return {"ok": True, "agent_id": agent_id, "slug": slug, "image_version": image.version}
