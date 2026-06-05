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

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from cloud.auth.deps import require_admin
from cloud.config import get_settings
from cloud.db.models import Agent, AuditLog, LunaImage, User
from cloud.db.session import get_session as get_db_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
async def add_admin(body: AddAdminRequest, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        user = (await db.execute(
            select(User).where(User.email == body.email.strip().lower())
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        if user.is_admin:
            return {"id": str(user.id), "email": user.email, "name": user.name, "already": True}

        user.is_admin = True
        db.add(AuditLog(
            actor_user_id=admin.id, action="admin.add_admin",
            target=str(user.id), metadata_={"email": user.email},
        ))
        await db.commit()
    return {"id": str(user.id), "email": user.email, "name": user.name}


@router.delete("/admins/{user_id}")
async def remove_admin(user_id: str, admin: User = Depends(require_admin)):
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
        db.add(AuditLog(
            actor_user_id=admin.id, action="admin.remove_admin",
            target=str(target.id), metadata_={"email": target.email},
        ))
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


@router.put("/images/{image_id}/config")
async def update_image_config(
    image_id: str, body: ImageConfigUpdate, admin: User = Depends(require_admin),
):
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")

        current = {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {})}
        patch = body.model_dump(exclude_none=True)
        for key, val in patch.items():
            if isinstance(val, dict) and isinstance(current.get(key), dict):
                current[key] = {**current[key], **val}
            else:
                current[key] = val

        img.image_config = current
        db.add(AuditLog(
            actor_user_id=admin.id, action="admin.update_image_config",
            target=str(img.id), metadata_={"version": img.version, "patch": patch},
        ))
        await db.commit()
    return current


@router.get("/plugin-meta")
async def get_plugin_meta(admin: User = Depends(require_admin)):
    return PLUGIN_META


@router.delete("/images/{image_id}")
async def delete_image(image_id: str, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
        if img.is_main:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete the main image")
        await db.delete(img)
        db.add(AuditLog(
            actor_user_id=admin.id, action="admin.delete_image",
            target=str(img.id), metadata_={"version": img.version},
        ))
        await db.commit()
    return {"ok": True}


@router.post("/images/{image_id}/set-main")
async def set_main_image(image_id: str, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
        if img.build_status != "built":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only built images can be set as main")

        await db.execute(
            LunaImage.__table__.update().values(is_main=False)
        )
        img.is_main = True
        db.add(AuditLog(
            actor_user_id=admin.id, action="admin.set_main_image",
            target=str(img.id), metadata_={"version": img.version},
        ))
        await db.commit()
    return {"ok": True, "version": img.version}


@router.post("/images/build")
async def build_image(admin: User = Depends(require_admin), version: str | None = None):
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
    authorization: str = Header(...),
):
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

        img.build_status = body.status
        img.git_sha = body.git_sha
        if body.build_run_id:
            img.build_run_id = body.build_run_id
        if body.status == "built":
            img.built_at = datetime.now(timezone.utc)
        if body.error:
            img.build_error = body.error
        await db.commit()

    return {"ok": True}


# ── Machines ─────────────────────────────────────────────────────────────────

@router.get("/machines")
async def list_machines(admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.runtime_ref.isnot(None)).order_by(Agent.created_at)
        )).scalars().all()

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
        })
    return result


@router.post("/machines/{machine_id}/update-image")
async def update_machine_image(machine_id: str, admin: User = Depends(require_admin)):
    """Update a single machine to the current main image."""
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
        db.add(AuditLog(
            actor_user_id=admin.id, action="admin.update_machine_image",
            target=machine_id, metadata_={"version": main_image.version, "agent": agent.slug},
        ))
        await db.commit()

    return {"ok": True, "version": main_image.version}


@router.post("/machines/migrate-all")
async def migrate_all_machines(admin: User = Depends(require_admin)):
    """Update all machines to the current main image."""
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
        db.add(AuditLog(
            actor_user_id=admin.id, action="admin.migrate_all",
            metadata_={"version": main_image.version, "updated": updated, "errors": len(errors)},
        ))
        await db.commit()

    return {"ok": True, "updated": updated, "errors": errors, "version": main_image.version}
