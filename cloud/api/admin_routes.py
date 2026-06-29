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
from cloud.db.models import Agent, AppSetting, AuditLog, LunaImage, User
from cloud.db.session import get_session as get_db_session
from cloud.gateway.registry import key_service_for_plugin

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


# ── Luna branches (build experimental branches) ───────────────────────────────

_branches_cache: dict[str, tuple[float, list[dict]]] = {}
_BRANCHES_TTL = 120.0
_MAX_BRANCH_COMPARES = 40  # bound GitHub calls; extra branches list without ahead/behind


def _slugify_branch(name: str) -> str:
    """Make a branch name safe for a docker tag fragment ([A-Za-z0-9_.-])."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-.")
    return slug[:80] or "branch"


def _gh_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("CLOUD_GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


LUNA_SDK_PATH = "luna_sdk/__init__.py"


async def _fetch_luna_sdk_contract(ref: str) -> tuple[int | None, int | None]:
    """Read (`__sdk_version__`, `__sdk_min_plugin_major__`) from luna_sdk at a ref.

    These are the target band for an upgrade-check. Best-effort; returns
    (None, None) on any failure so a build never blocks on it.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{LUNA_GITHUB_REPO}/contents/{LUNA_SDK_PATH}",
                params={"ref": ref}, headers=_gh_headers(),
            )
        if resp.status_code == 200:
            content = base64.b64decode(resp.json().get("content", "")).decode("utf-8")
            mj = re.search(r'__sdk_version__\s*=\s*"?(\d+)"?', content)
            mn = re.search(r'__sdk_min_plugin_major__\s*=\s*"?(\d+)"?', content)
            return (
                int(mj.group(1)) if mj else None,
                int(mn.group(1)) if mn else None,
            )
        log.warning("GitHub sdk-contract returned %s for ref %s", resp.status_code, ref)
    except Exception as exc:  # noqa: BLE001
        log.warning("GitHub sdk-contract fetch failed for %s: %s", ref, exc)
    return None, None


def _clean_commit_subjects(messages: list[str]) -> list[str]:
    """First lines of commit messages, dropping merge/version-bump noise."""
    out: list[str] = []
    for m in messages:
        subject = (m or "").strip().splitlines()[0].strip() if m else ""
        if not subject:
            continue
        low = subject.lower()
        if low.startswith("merge ") or low.startswith("merge branch") or low.startswith("merge pull"):
            continue
        out.append(subject)
    return out


async def _fetch_release_notes(ref: str, prev_sha: str | None) -> str | None:
    """Succinct changelog (markdown bullets) for what's new on `ref`.

    If `prev_sha` is known, diff `prev_sha...ref`; otherwise list the most recent
    commits on `ref`. Best-effort — returns None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            subjects: list[str] = []
            if prev_sha:
                resp = await client.get(
                    f"https://api.github.com/repos/{LUNA_GITHUB_REPO}/compare/{prev_sha}...{ref}",
                    headers=_gh_headers(),
                )
                if resp.status_code == 200:
                    commits = resp.json().get("commits", []) or []
                    subjects = _clean_commit_subjects([c.get("commit", {}).get("message", "") for c in commits])
            if not subjects:
                resp = await client.get(
                    f"https://api.github.com/repos/{LUNA_GITHUB_REPO}/commits",
                    params={"sha": ref, "per_page": 20}, headers=_gh_headers(),
                )
                if resp.status_code == 200:
                    subjects = _clean_commit_subjects([c.get("commit", {}).get("message", "") for c in resp.json()])
        if not subjects:
            return None
        subjects = subjects[:20]
        return "\n".join(f"- {s}" for s in subjects)
    except Exception as exc:  # noqa: BLE001
        log.warning("GitHub release-notes fetch failed for %s: %s", ref, exc)
        return None


async def _fetch_luna_ref_info(ref: str) -> tuple[str | None, str | None]:
    """Return (luna __version__, head commit sha) for a branch/ref via GitHub."""
    version: str | None = None
    sha: str | None = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            cresp = await client.get(
                f"https://api.github.com/repos/{LUNA_GITHUB_REPO}/contents/{LUNA_VERSION_PATH}",
                params={"ref": ref}, headers=_gh_headers(),
            )
            if cresp.status_code == 200:
                content = base64.b64decode(cresp.json().get("content", "")).decode("utf-8")
                m = re.search(r'__version__\s*=\s*"(.+?)"', content)
                version = m.group(1) if m else None
            bresp = await client.get(
                f"https://api.github.com/repos/{LUNA_GITHUB_REPO}/branches/{ref}",
                headers=_gh_headers(),
            )
            if bresp.status_code == 200:
                sha = bresp.json().get("commit", {}).get("sha")
    except Exception as exc:  # noqa: BLE001
        log.warning("GitHub ref-info fetch failed for %s: %s", ref, exc)
    return version, sha


async def _list_luna_branches() -> list[dict]:
    """List luna repo branches with merge status vs main. Short-TTL cached.

    Each entry: {name, commit_sha, merged, ahead_by, behind_by}. `merged` means
    the branch has no commits beyond main (ahead_by == 0). Never raises.
    """
    now = time.time()
    cached = _branches_cache.get("luna")
    if cached and now - cached[0] < _BRANCHES_TTL:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{LUNA_GITHUB_REPO}/branches",
                params={"per_page": 100}, headers=_gh_headers(),
            )
            resp.raise_for_status()
            raw = resp.json()
            out: list[dict] = []
            compares = 0
            for b in raw:
                name = b.get("name")
                if not name:
                    continue
                entry = {
                    "name": name,
                    "commit_sha": b.get("commit", {}).get("sha"),
                    "merged": name == "main",
                    "ahead_by": 0,
                    "behind_by": 0,
                }
                if name != "main" and compares < _MAX_BRANCH_COMPARES:
                    compares += 1
                    try:
                        cmp = await client.get(
                            f"https://api.github.com/repos/{LUNA_GITHUB_REPO}/compare/main...{name}",
                            headers=_gh_headers(),
                        )
                        if cmp.status_code == 200:
                            cj = cmp.json()
                            entry["ahead_by"] = cj.get("ahead_by", 0)
                            entry["behind_by"] = cj.get("behind_by", 0)
                            entry["merged"] = cj.get("ahead_by", 0) == 0
                    except Exception:  # noqa: BLE001
                        pass
            # Order: unmerged (experimental) first, main pinned at top, then name.
                out.append(entry)
        out.sort(key=lambda e: (e["name"] != "main", e["merged"], e["name"]))
        _branches_cache["luna"] = (now, out)
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("GitHub branches fetch failed: %s", exc)
        return cached[1] if cached else [{"name": "main", "commit_sha": None, "merged": True, "ahead_by": 0, "behind_by": 0}]


# This list is ONLY the in-tree plugins that ship inside luna core, i.e. the ones
# present at every boot regardless of any marketplace selection. Plugins that were
# decoupled from core onto the SDK (charts, web-access, files, mcp, recall,
# funnelfighters, …) are NOT in the image unless baked via the "Plugin Set"
# picker / image Defaults — they are governed there, not by this hardcoded list.
# `source` is kept for callers that read it; every entry here is "in-tree".
PLUGIN_META = [
    {"key": "plugin_vault", "name": "Vault", "description": "Encrypted credential storage", "required": True, "source": "in-tree"},
    {"key": "plugin_memory", "name": "Memory", "description": "Long-term semantic recall", "required": True, "source": "in-tree"},
    {"key": "plugin_identity", "name": "Identity", "description": "Agent name, persona, settings", "required": True, "source": "in-tree"},
    {"key": "plugin_brain", "name": "Brain", "description": "Live neural activity visualization", "required": False, "source": "in-tree"},
    {"key": "plugin_meta", "name": "Meta", "description": "Toggle other plugins at runtime", "required": True, "source": "in-tree"},
    {"key": "plugin_approvals", "name": "Approvals", "description": "Gates risky actions for owner consent", "required": True, "source": "in-tree"},
    {"key": "plugin_web", "name": "Web Server", "description": "Core HTTP server and auth", "required": True, "source": "in-tree"},
]

# ── Plugin set (Plan 019) ─────────────────────────────────────────────────────
# The official marketplace is the only catalog we read. The admin picks a subset
# of leaf plugins to bake into the image (image_config.plugin_set); the build
# fetches + sha256-verifies them. Connectors carry PyPI deps and hit the
# unresolved dependency-isolation problem (Luna 008.5 §5), so they are not
# bakeable yet and are rejected on save.
OFFICIAL_MARKETPLACE_URL = os.environ.get(
    "CLOUD_MARKETPLACE_URL", "https://luna-marketplaces.onrender.com/mp/official/"
)

# Marketplace plugin names (hyphenated) that are NOT bakeable this round.
NON_BAKEABLE_PLUGINS = {
    "plugin-monday", "plugin-render", "plugin-cloudflare",
}


def _is_bakeable(name: str) -> bool:
    """A marketplace plugin is bakeable unless it's a known connector (deps)."""
    return _norm_plugin_name(name) not in {
        _norm_plugin_name(n) for n in NON_BAKEABLE_PLUGINS
    }


def _norm_plugin_name(name: str) -> str:
    """Normalise a plugin name for comparison (hyphen/underscore agnostic)."""
    return (name or "").strip().lower().replace("_", "-")


# Short-TTL cache for the marketplace catalog (Render Starter has cold starts).
_catalog_cache: dict[str, tuple[float, list[dict]]] = {}
_CATALOG_TTL = 120.0

DEFAULT_IMAGE_CONFIG = {
    "machine": {
        "cpu_kind": "shared",
        "cpus": 1,
        "memory_mb": 1024,
        "region": "sjc",
    },
    "models": {
        # Plan 018: empty = inherit the catalog default (the model marked
        # recommended_default for its kind). An image may pin primary/fast to
        # override the catalog default; a machine may override the image.
        "primary": {},
        "fast": {},
    },
    "plugins": {
        "plugin_vault": True,
        "plugin_memory": True,
        "plugin_identity": True,
        "plugin_brain": True,
        "plugin_meta": True,
        "plugin_approvals": True,
        "plugin_web": True,
    },
    # Plan 019: marketplace plugins baked into this image. Empty = the UI will
    # pre-select the curated leaf set on first open; the build falls back to
    # plugin-set.toml until an explicit selection is saved.
    "plugin_set": [],
    "env": {},
}


# ── Image defaults (Plan 020) ─────────────────────────────────────────────────
# The admin-editable defaults (default model + default plugin set) live in the
# app_settings singleton under this key. DEFAULT_IMAGE_CONFIG above is the
# hardcoded base; the stored defaults overlay it. Resolution for an image is:
#   base  <  stored image_defaults  <  the image's own image_config.
IMAGE_DEFAULTS_KEY = "image_defaults"


async def _get_app_setting(db: AsyncSession, key: str) -> dict:
    row = (await db.execute(
        select(AppSetting).where(AppSetting.key == key)
    )).scalar_one_or_none()
    return row.value if row and isinstance(row.value, dict) else {}


async def _set_app_setting(db: AsyncSession, key: str, value: dict) -> None:
    row = (await db.execute(
        select(AppSetting).where(AppSetting.key == key)
    )).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def _overlay(base: dict, overlay: dict) -> dict:
    """Shallow merge with one level of dict-merge (matches image_config shape)."""
    out = {**base}
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


async def _default_image_config(db: AsyncSession) -> dict:
    """Base config overlaid with the admin-stored image defaults (Plan 020)."""
    return _overlay(DEFAULT_IMAGE_CONFIG, await _get_app_setting(db, IMAGE_DEFAULTS_KEY))


def _image_dict(img: LunaImage, agent_count: int = 0, default_cfg: dict | None = None) -> dict:
    base = default_cfg if default_cfg is not None else DEFAULT_IMAGE_CONFIG
    return {
        "id": str(img.id),
        "version": img.version,
        "registry_tag": img.registry_tag,
        "is_main": img.is_main,
        "build_status": img.build_status,
        "build_run_id": img.build_run_id,
        "build_error": img.build_error,
        "git_sha": img.git_sha,
        "git_branch": img.git_branch or "main",
        "created_at": img.created_at.isoformat() if img.created_at else None,
        "built_at": img.built_at.isoformat() if img.built_at else None,
        "agent_count": agent_count,
        "image_config": {**base, **(img.image_config or {})},
        "cache_warmed_at": img.cache_warmed_at.isoformat() if img.cache_warmed_at else None,
        "sdk_major": img.sdk_major,
        "sdk_min_major": img.sdk_min_major,
        "release_notes": img.release_notes,
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

        default_cfg = await _default_image_config(db)

    return [_image_dict(img, counts.get(img.version, 0), default_cfg) for img in images]


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
        default_cfg = await _default_image_config(db)

    return _image_dict(img, agent_count or 0, default_cfg)


@router.get("/images/{image_id}/config")
async def get_image_config(image_id: str, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
        default_cfg = await _default_image_config(db)
    return {**default_cfg, **(img.image_config or {})}


class ImageConfigUpdate(BaseModel):
    machine: dict | None = None
    models: dict | None = None
    plugins: dict | None = None
    env: dict | None = None
    services: dict | None = None
    plugin_set: list[dict] | None = None


def _validate_plugin_set(entries: list[dict]) -> list[dict]:
    """Validate a plugin_set selection from the admin UI.

    Each entry must carry name/version/sha256 (sha captured from index.json at
    selection time, so the build is pinned + reproducible) and name a bakeable
    leaf plugin. Returns the normalised list; raises 400 on any bad entry.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for raw in entries:
        if not isinstance(raw, dict):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "plugin_set entries must be objects")
        name = str(raw.get("name") or "").strip()
        version = str(raw.get("version") or "").strip()
        sha256 = str(raw.get("sha256") or "").strip().lower()
        if not name or not version or not sha256:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"plugin_set entry needs name/version/sha256: {raw!r}",
            )
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid sha256 for {name}")
        if not _is_bakeable(name):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"plugin '{name}' is not bakeable yet (connectors carry deps; "
                "see Luna 008.5 dependency-isolation)",
            )
        key = _norm_plugin_name(name)
        if key in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"duplicate plugin '{name}' in set")
        seen.add(key)
        out.append({"name": name, "version": version, "sha256": sha256})
    return out


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

        before = {**(await _default_image_config(db)), **(img.image_config or {})}
        patch = body.model_dump(exclude_none=True)
        if "plugin_set" in patch:
            patch["plugin_set"] = _validate_plugin_set(patch["plugin_set"])
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


# ── Plugin-set catalog (Plan 019) ─────────────────────────────────────────────

async def _fetch_marketplace_catalog() -> list[dict]:
    """Fetch + normalise the official marketplace index. Short-TTL cached.

    Returns [{name, version, description, sha256, bakeable}]. Never raises to the
    caller — on a marketplace failure it serves the last cached value (or []),
    so the admin page degrades instead of 500-ing.
    """
    now = time.time()
    cached = _catalog_cache.get("official")
    if cached and now - cached[0] < _CATALOG_TTL:
        return cached[1]

    url = OFFICIAL_MARKETPLACE_URL.rstrip("/") + "/index.json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        entries = []
        for p in data.get("plugins", []):
            name = p.get("name")
            if not name:
                continue
            entries.append({
                "name": name,
                "version": p.get("version", ""),
                "description": p.get("description", ""),
                "sha256": p.get("sha256", ""),
                "bakeable": _is_bakeable(name),
                # Which gateway service this plugin needs a key for (None = no
                # external key — the UI hides the key control). Plan 026.
                "key_service": key_service_for_plugin(name),
            })
        entries.sort(key=lambda e: e["name"])
        _catalog_cache["official"] = (now, entries)
        return entries
    except Exception as exc:  # noqa: BLE001 — page must not break on marketplace down
        log.warning("marketplace catalog fetch failed (%s): %s", url, exc)
        return cached[1] if cached else []


@router.get("/marketplace/catalog")
async def marketplace_catalog(
    q: str | None = Query(default=None),
    admin: User = Depends(require_admin),
):
    plugins = await _fetch_marketplace_catalog()
    if q:
        needle = q.strip().lower()
        plugins = [
            p for p in plugins
            if needle in p["name"].lower() or needle in (p.get("description") or "").lower()
        ]
    return {"marketplace": OFFICIAL_MARKETPLACE_URL, "plugins": plugins}


# ── Image defaults (Plan 020) ─────────────────────────────────────────────────

class ImageDefaultsUpdate(BaseModel):
    models: dict | None = None
    plugin_set: list[dict] | None = None


def _validate_default_models(models: dict) -> dict:
    """Normalise the default-model selection. Each head is {} (inherit catalog)
    or {provider, model}. Anything else is rejected."""
    out: dict = {}
    for head in ("primary", "fast"):
        val = models.get(head)
        if val in (None, {}):
            out[head] = {}
            continue
        if not isinstance(val, dict):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{head} must be an object")
        provider = str(val.get("provider") or "").strip()
        model = str(val.get("model") or "").strip()
        if not provider or not model:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{head} needs both provider and model (or be empty to inherit)",
            )
        out[head] = {"provider": provider, "model": model}
    return out


@router.get("/defaults")
async def get_image_defaults(admin: User = Depends(require_admin)):
    """The admin-editable image defaults (default model + default plugin set),
    resolved over the hardcoded base so the UI always sees a full shape."""
    async with get_db_session() as db:
        cfg = await _default_image_config(db)
    return {"models": cfg.get("models", {}), "plugin_set": cfg.get("plugin_set", [])}


@router.get("/defaults/env")
async def get_default_env(admin: User = Depends(require_admin)):
    """Plan 029: the env-var template every NEW machine receives. Dynamic
    per-agent values are placeholders; nothing here is a real secret."""
    from cloud.provisioning.env_manifest import default_env_manifest
    from cloud.provisioning.model_catalog import resolve_default_heads, system_catalog

    async with get_db_session() as db:
        cfg = await _default_image_config(db)
        catalog = await system_catalog(db)
        heads = resolve_default_heads(catalog, cfg, None)
        cfg = {**cfg, "models": {"primary": heads["primary"], "fast": heads["fast"]}}
        entries = await default_env_manifest(db, cfg)
    return {"entries": entries}


@router.put("/defaults")
async def update_image_defaults(
    body: ImageDefaultsUpdate, request: Request, admin: User = Depends(require_admin),
):
    ip = _client_ip(request)
    patch = body.model_dump(exclude_none=True)
    if "plugin_set" in patch:
        patch["plugin_set"] = _validate_plugin_set(patch["plugin_set"])
    if "models" in patch:
        patch["models"] = _validate_default_models(patch["models"])

    async with get_db_session() as db:
        before = await _get_app_setting(db, IMAGE_DEFAULTS_KEY)
        current = {**before, **patch}
        await _set_app_setting(db, IMAGE_DEFAULTS_KEY, current)
        await _audit(db, action="image.defaults_updated", actor=admin, actor_ip=ip,
                     target=IMAGE_DEFAULTS_KEY, metadata={"patch": patch},
                     before_state=before, after_state=current)
        await db.commit()
        cfg = await _default_image_config(db)
    return {"models": cfg.get("models", {}), "plugin_set": cfg.get("plugin_set", [])}


def _normalize_plugin_set(entries: list[dict] | None) -> set[tuple[str, str]]:
    """A plugin set as an order-insensitive {(name, version)} set for comparison.
    Hyphen/underscore agnostic on the name so `plugin-files` == `plugin_files`."""
    out: set[tuple[str, str]] = set()
    for e in entries or []:
        name = _norm_plugin_name(e.get("name", ""))
        version = (e.get("version") or "").strip()
        if name:
            out.add((name, version))
    return out


@router.get("/defaults/stale")
async def defaults_stale(admin: User = Depends(require_admin)):
    """Plan 032: is the current Defaults plugin_set baked into the main image?

    `stale` is true when the current defaults' plugin_set differs from what the
    main built image actually baked (its `image_config.plugin_set`, or the
    plugin-set.toml seed for images built before Plan 032 snapshotting). A stale
    state means a rebake of main is required for plugin-set changes to land.
    """
    async with get_db_session() as db:
        cfg = await _default_image_config(db)
        current = cfg.get("plugin_set", []) or []

        main_img = (await db.execute(
            select(LunaImage).where(
                LunaImage.is_main == True,  # noqa: E712
                LunaImage.build_status == "built",
            )
        )).scalar_one_or_none()

    if main_img is None:
        # No built main yet — nothing to be stale against.
        return {"stale": False, "main_version": None, "main_image_id": None,
                "current_count": len(current), "baked_count": 0}

    baked = (main_img.image_config or {}).get("plugin_set") or []
    if not baked:
        # Pre-032 image (empty config) baked the seed.
        baked = _read_plugin_set_seed()

    stale = _normalize_plugin_set(current) != _normalize_plugin_set(baked)
    return {
        "stale": stale,
        "main_version": main_img.version,
        "main_image_id": str(main_img.id),
        "current_count": len(current),
        "baked_count": len(baked),
    }


def _read_plugin_set_seed() -> list[dict]:
    """Read plugin-set.toml at repo root → [{name, version, sha256}] (or [])."""
    import tomllib
    seed_path = Path(__file__).resolve().parents[2] / "plugin-set.toml"
    if not seed_path.exists():
        return []
    try:
        data = tomllib.loads(seed_path.read_text())
    except Exception as exc:  # noqa: BLE001
        log.warning("plugin-set.toml parse failed: %s", exc)
        return []
    out = []
    for p in data.get("plugins", []):
        if p.get("name") and p.get("version") and p.get("sha256"):
            out.append({"name": p["name"], "version": p["version"], "sha256": p["sha256"]})
    return out


@router.get("/images/{image_id}/plugin-set")
async def get_image_plugin_set(
    image_id: str,
    authorization: str = Header(None),
):
    """Resolve the baked plugin set for an image — consumed by the build workflow.

    Auth: the admin webhook secret (same as build-complete), because GitHub
    Actions calls this with no user session. Returns the saved selection, or the
    plugin-set.toml seed when the image has none yet.
    """
    settings = get_settings()
    if authorization != f"Bearer {settings.admin_webhook_secret}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook secret")

    async with get_db_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.id == uuid.UUID(image_id))
        )).scalar_one_or_none()
        if not img:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")

    selection = (img.image_config or {}).get("plugin_set") or []
    if not selection:
        selection = _read_plugin_set_seed()
    return {"marketplace": OFFICIAL_MARKETPLACE_URL, "plugins": selection}


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
        image_config = {**(await _default_image_config(db)), **(img.image_config or {})}

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
        image_config = {**(await _default_image_config(db)), **(img.image_config or {})}

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


@router.get("/luna/branches")
async def list_luna_branches(admin: User = Depends(require_admin)):
    """List luna repo branches so the admin can build an experimental branch."""
    return {"repo": LUNA_GITHUB_REPO, "branches": await _list_luna_branches()}


@router.post("/images/build")
async def build_image(
    request: Request,
    admin: User = Depends(require_admin),
    version: str | None = None,
    branch: str = "main",
    force: bool = False,
):
    ip = _client_ip(request)
    settings = get_settings()
    branch = (branch or "main").strip()

    git_sha: str | None = None
    if branch == "main":
        # Release build: version = luna main's __version__.
        if not version:
            version = (await _fetch_luna_version_from_github())[0]
        if not version:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot determine Luna version")
        base_version = version
    else:
        # Experimental branch build: qualify the tag with branch + short sha so it
        # never collides with main or other branches, and each commit is distinct.
        base_version, git_sha = await _fetch_luna_ref_info(branch)
        if not git_sha:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Luna branch '{branch}' not found")
        if not base_version:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Cannot read Luna version from branch '{branch}'",
            )
        version = f"{base_version}-{_slugify_branch(branch)}-{git_sha[:7]}"

    fly_app = os.environ.get("FLY_APP", "luna-agents")
    registry_tag = f"registry.fly.io/{fly_app}:{version}"

    # 024: capture the upgrade-preview contract for this image — the SDK band the
    # target ships (drives upgrade-check) + a succinct changelog. Best-effort.
    sdk_major, sdk_min_major = await _fetch_luna_sdk_contract(branch)
    if branch == "main" and not git_sha:
        _, git_sha = await _fetch_luna_ref_info("main")

    async with get_db_session() as db:
        existing = (await db.execute(
            select(LunaImage).where(LunaImage.version == version)
        )).scalar_one_or_none()
        # Plan 032: `force` rebakes an already-built version in place (same tag),
        # e.g. to re-bake main with updated defaults without bumping Luna. The
        # existing record is replaced below; we carry its `is_main` forward so a
        # rebaked main stays main. A `building` image is never force-replaced
        # (a build is already in flight).
        was_main = bool(existing.is_main) if existing else False
        if existing and existing.build_status == "building":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Image {version} is already building",
            )
        if existing and existing.build_status == "built" and not force:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Image {version} already exists (status: {existing.build_status})",
            )

        prev_main = (await db.execute(
            select(LunaImage).where(
                LunaImage.is_main == True,  # noqa: E712
                LunaImage.build_status == "built",
            )
        )).scalar_one_or_none()
        release_notes = await _fetch_release_notes(branch, prev_main.git_sha if prev_main else None)

        # Plan 032: snapshot the resolved defaults' plugin_set into THIS image's
        # config so the build bakes the admin Defaults (not the seed) and the
        # image permanently records what it baked. Empty defaults → [] → the
        # plugin-set endpoint still falls back to the plugin-set.toml seed.
        default_cfg = await _default_image_config(db)
        baked_plugin_set = default_cfg.get("plugin_set", []) or []

        img = LunaImage(
            version=version,
            registry_tag=registry_tag,
            build_status="building",
            created_by=admin.id,
            git_branch=branch,
            git_sha=git_sha,
            sdk_major=sdk_major,
            sdk_min_major=sdk_min_major,
            release_notes=release_notes,
            image_config={"plugin_set": baked_plugin_set},
            is_main=was_main,
        )
        if existing:
            await db.delete(existing)
            await db.flush()
        db.add(img)
        await db.commit()
        await db.refresh(img)
        image_id = str(img.id)

        await _audit(db, action="image.build_triggered", actor=admin, actor_ip=ip,
                     target=image_id, metadata={"version": version, "registry_tag": registry_tag,
                                                 "branch": branch, "base_version": base_version},
                     after_state={"version": version, "build_status": "building", "branch": branch})
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
                        "inputs": {
                            "version": version,
                            "image_id": image_id,
                            "branch": branch,
                            "base_version": base_version,
                        },
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
    from cloud.provisioning.model_catalog import resolve_default_heads, system_catalog

    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.runtime_ref.isnot(None)).order_by(Agent.created_at)
        )).scalars().all()

        # Build a version → image_config map so the per-row resolver has the image default.
        versions = {a.image_version for a in agents if a.image_version}
        images = (await db.execute(
            select(LunaImage).where(LunaImage.version.in_(versions))
        )).scalars().all() if versions else []
        _default_cfg = await _default_image_config(db)
        image_config_by_version = {
            img.version: {**_default_cfg, **(img.image_config or {})}
            for img in images
        }
        catalog = await system_catalog(db)

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

        # Plan 018: catalog-validated default heads + per-role override.
        models_resolved = resolve_default_heads(catalog, image_cfg, agent.config_overrides)
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
            "primary_model": models_resolved["primary"],
            "fast_model": models_resolved["fast"],
            "primary_model_override": primary_override,
            "fast_model_override": fast_override,
        })
    return result


@router.get("/machines/{machine_id}/env")
async def get_machine_env(machine_id: str, admin: User = Depends(require_admin)):
    """Plan 029: the LIVE env on a machine (classified + secrets masked), plus
    any expected-but-missing keys vs the provisioning template."""
    from cloud.provisioning.env_manifest import default_env_manifest, live_machine_env
    from cloud.provisioning.model_catalog import resolve_default_heads, system_catalog

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.runtime_ref == machine_id)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found")
        img = None
        if agent.image_version:
            img = (await db.execute(
                select(LunaImage).where(LunaImage.version == agent.image_version)
            )).scalar_one_or_none()
        cfg = {**(await _default_image_config(db)), **((img.image_config if img else None) or {})}
        catalog = await system_catalog(db)
        heads = resolve_default_heads(catalog, cfg, agent.config_overrides)
        cfg = {**cfg, "models": {"primary": heads["primary"], "fast": heads["fast"]}}
        expected = await default_env_manifest(db, cfg)
    expected_names = {e["name"] for e in expected}

    config_env: dict = {}
    fly_state = None
    fly_available = bool(os.environ.get("FLY_API_TOKEN"))
    if fly_available and agent.runtime_ref:
        try:
            from cloud.runtime.fly_machines import FlyMachinesRuntime
            fly = FlyMachinesRuntime()
            rec = await fly.describe(agent.runtime_ref)
            config_env = ((rec or {}).get("config") or {}).get("env") or {}
            fly_state = (rec or {}).get("state")
        except Exception as e:  # pragma: no cover - network
            log.warning("env describe failed for %s: %s", machine_id, e)

    result = live_machine_env(config_env, expected_names)
    result.update({
        "agent_slug": agent.slug,
        "agent_name": agent.name,
        "machine_id": machine_id,
        "fly_state": fly_state,
        "fly_available": fly_available,
    })
    return result


@router.post("/machines/env/backfill")
async def backfill_machine_env(
    request: Request,
    dry_run: bool = True,
    admin: User = Depends(require_admin),
):
    """Plan 029: push the gateway env block to any machine that is missing it.

    Only touches machines whose LIVE env lacks the LUNA_GATEWAY_URL/TOKEN pair,
    so healthy machines are skipped — no token rotation and no needless restart.
    update_machine_env merges (never wipes) and restarts the machine in place.
    dry_run=true (default) reports what WOULD change without touching anything.
    """
    if not os.environ.get("FLY_API_TOKEN"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "FLY_API_TOKEN not configured in this environment")
    from cloud.api.gateway_env_delta import _agent_image_config
    from cloud.gateway.provision_env import build_gateway_env
    from cloud.runtime.fly_machines import FlyMachinesRuntime

    fly = FlyMachinesRuntime()
    sentinels = ("LUNA_GATEWAY_URL", "LUNA_GATEWAY_TOKEN")

    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.runtime_ref.is_not(None))
        )).scalars().all()
        targets = [(a.id, a.slug, a.name, a.runtime_ref, a.runtime_kind) for a in agents]

    results: list[dict] = []
    updated = skipped = errored = 0
    for agent_id, slug, name, ref, kind in targets:
        if not (kind or "").startswith("fly"):
            continue
        row: dict = {"slug": slug, "name": name, "machine_id": ref}
        try:
            rec = await fly.describe(ref)
            if not rec:
                row["status"] = "machine_gone"
                errored += 1
                results.append(row)
                continue
            live = (rec.get("config") or {}).get("env") or {}
            missing = [k for k in sentinels if k not in live]
            row["missing"] = missing
            if not missing:
                row["status"] = "up_to_date"
                skipped += 1
                results.append(row)
                continue
            if dry_run:
                row["status"] = "would_update"
                results.append(row)
                continue
            async with get_db_session() as db:
                agent = (await db.execute(
                    select(Agent).where(Agent.id == agent_id)
                )).scalar_one()
                image_config = await _agent_image_config(db, agent)
                env = await build_gateway_env(
                    db, agent.id, image_config=image_config,
                    agent_overrides=agent.config_overrides,
                )
                await db.commit()
            await fly.update_machine_env(ref, env)
            row["status"] = "updated"
            row["pushed_keys"] = sorted(env.keys())
            updated += 1
        except Exception as e:  # noqa: BLE001 — report per machine, never abort the run
            log.error("env backfill failed for %s (%s): %s", slug, ref, e)
            row["status"] = f"error: {type(e).__name__}: {e}"
            errored += 1
        results.append(row)

    if not dry_run:
        async with get_db_session() as db:
            await _audit(db, action="machines.env_backfill", actor=admin,
                         actor_ip=_client_ip(request), target="*",
                         metadata={"updated": updated, "skipped": skipped, "errored": errored})
            await db.commit()

    return {
        "dry_run": dry_run,
        "total": len(results),
        "updated": updated,
        "skipped": skipped,
        "errored": errored,
        "machines": results,
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
    LUNA_PRIMARY_MODEL / LUNA_FAST_MODEL + LUNA_MODEL_CATALOG env vars to the
    live machine."""
    from cloud.provisioning.model_catalog import resolve_default_heads, system_catalog

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
        image_cfg = {**(await _default_image_config(db)), **(img.image_config or {} if img else {})}
        catalog = await system_catalog(db)
        resolved = resolve_default_heads(catalog, image_cfg, agent.config_overrides)

        await _audit(db, action="machine.models_updated", actor=admin, actor_ip=ip,
                     target=machine_id,
                     metadata={"agent": agent.slug, "resolved": resolved},
                     before_state={"config_overrides": before},
                     after_state={"config_overrides": agent.config_overrides, "resolved_models": resolved})
        await db.commit()

    if os.environ.get("FLY_API_TOKEN") and agent.runtime_kind in ("fly", "fly-machines"):
        import json as _json
        from cloud.runtime.fly_machines import FlyMachinesRuntime
        fly = FlyMachinesRuntime()
        env_updates = {
            "LUNA_PRIMARY_MODEL": f"{resolved['primary']['provider']}:{resolved['primary']['model']}",
            "LUNA_FAST_MODEL": f"{resolved['fast']['provider']}:{resolved['fast']['model']}",
            "LUNA_MODEL_CATALOG": _json.dumps(catalog),
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
    """Update a single machine to a chosen built image.

    Accepts an optional ``{"image_id": ...}`` body to target any built image;
    when omitted, falls back to the current main image (legacy behavior).
    """
    ip = _client_ip(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    target_image_id = (body or {}).get("image_id")

    async with get_db_session() as db:
        if target_image_id:
            target_image = (await db.execute(
                select(LunaImage).where(
                    LunaImage.id == target_image_id,
                    LunaImage.build_status == "built",
                )
            )).scalar_one_or_none()
            if not target_image:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Target image not found or not built")
        else:
            target_image = (await db.execute(
                select(LunaImage).where(LunaImage.is_main == True, LunaImage.build_status == "built")  # noqa: E712
            )).scalar_one_or_none()
            if not target_image:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "No main image set")
        target_tag = target_image.registry_tag
        target_version = target_image.version

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
        await fly.update_machine_image(machine_id, target_tag)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to update machine: {e}")

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.runtime_ref == machine_id)
        )).scalar_one()
        agent.image_version = target_version
        await _audit(db, action="machine.image_updated", actor=admin, actor_ip=ip,
                     target=machine_id, metadata={"version": target_version, "agent": agent.slug},
                     before_state={"version": old_version},
                     after_state={"version": target_version})
        await db.commit()

    return {"ok": True, "version": target_version}


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


# ── Plan 025.5: persistent files — backfill Fly volumes onto existing machines ──
#
# A Fly volume can only be mounted by a machine in the volume's *zone*, and a
# freshly-created volume lands in an arbitrary zone while an existing machine is
# zone-pinned. So we can't add a mount to a live machine in place ("volume does
# not exist"). Instead we destroy the machine and re-provision it: the provision
# path creates the volume first and Fly co-locates the new machine in its zone.
# The agent's durable state (per-agent Postgres DB + R2) is untouched; only the
# ephemeral machine (which never had durable files) is recreated.


async def _main_image_id(db) -> str | None:
    img = (await db.execute(
        select(LunaImage).where(LunaImage.is_main == True,  # noqa: E712
                                LunaImage.build_status == "built")
    )).scalar_one_or_none()
    return str(img.id) if img else None


async def _wait_machine_gone(fly, machine_id: str, timeout: int = 30) -> None:
    """Poll until a destroyed machine is really gone, so re-provision can reuse the name."""
    import asyncio
    client = fly._get_client()
    for _ in range(timeout):
        resp = await client.get(f"/machines/{machine_id}")
        if resp.status_code == 404:
            return
        if resp.json().get("state") in ("destroyed", "destroying"):
            await asyncio.sleep(1)
            continue
        await asyncio.sleep(1)


async def _recreate_with_volume(fly, account_id, agent_id, machine_id: str, image_id: str,
                                allow_missing: bool = False) -> dict:
    """Idempotently give one agent a persistent volume by destroy + re-provision.

    Returns a dict describing the outcome (skipped + reason, or the new machine
    id / volume id). A dead/missing machine is skipped unless ``allow_missing``
    is set, in which case the agent is (re)provisioned fresh — used to restore an
    agent whose machine has already gone away.
    """
    client = fly._get_client()
    resp = await client.get(f"/machines/{machine_id}")
    if resp.status_code == 404:
        if not allow_missing:
            return {"skipped": True, "reason": "machine_not_found"}
    else:
        resp.raise_for_status()
        machine = resp.json()
        state = machine.get("state")
        mounts = (machine.get("config") or {}).get("mounts") or []
        if any(m.get("path") == "/workspace" for m in mounts):
            return {"skipped": True, "reason": "already_mounted", "volume_id": mounts[0].get("volume")}
        if state not in ("started", "stopped") and not allow_missing:
            return {"skipped": True, "reason": f"machine_{state}"}
        await client.delete(f"/machines/{machine_id}?force=true")
        await _wait_machine_gone(fly, machine_id)

    from cloud.provisioning.workflow import provision_luna_for_account_with_image
    agent = await provision_luna_for_account_with_image(
        str(account_id), agent_id=str(agent_id), image_id=image_id,
    )
    return {
        "skipped": False,
        "new_machine_id": getattr(agent, "runtime_ref", None),
        "volume_id": getattr(agent, "volume_id", None),
        "status": getattr(agent, "status", None),
    }


@router.post("/machines/{machine_id}/attach-volume")
async def attach_machine_volume(machine_id: str, request: Request, admin: User = Depends(require_admin)):
    """Give one existing agent a persistent Fly volume (destroy + re-provision).

    Idempotent: a machine already mounting /workspace is skipped. Pass
    ``{"dry_run": true}`` to preview without mutating.
    """
    ip = _client_ip(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    dry_run = bool((body or {}).get("dry_run"))
    force = bool((body or {}).get("force"))

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.runtime_ref == machine_id)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No agent found for this machine")
        agent_slug = agent.slug
        agent_id = agent.id
        account_id = agent.account_id
        already = agent.volume_id
        image_id = await _main_image_id(db)

    if dry_run:
        return {"ok": True, "dry_run": True, "machine_id": machine_id,
                "agent": agent_slug, "would_attach": not already, "current_volume_id": already}

    if not os.environ.get("FLY_API_TOKEN"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Fly API not configured")
    if not image_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "No built main image to re-provision onto")

    from cloud.runtime.fly_machines import FlyMachinesRuntime
    fly = FlyMachinesRuntime()
    try:
        result = await _recreate_with_volume(fly, account_id, agent_id, machine_id, image_id,
                                             allow_missing=force)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to attach volume: {e}")

    async with get_db_session() as db:
        await _audit(db, action="machine.volume_attached", actor=admin, actor_ip=ip,
                     target=machine_id,
                     metadata={"agent": agent_slug, "volume_id": result.get("volume_id"),
                               "skipped": result.get("skipped"), "reason": result.get("reason")})
        await db.commit()
    return {"ok": True, **result, "agent": agent_slug}


@router.post("/machines/attach-volume-all")
async def attach_volume_all(request: Request, admin: User = Depends(require_admin)):
    """Backfill persistent volumes onto every live machine (destroy + re-provision).

    Serial + idempotent: already-mounted and dead machines are skipped. Pass
    ``{"dry_run": true}`` to return the computed list without mutating. Because
    each agent is recreated (~1 min), prefer driving the per-machine endpoint in
    a loop for large fleets to stay under HTTP timeouts.
    """
    ip = _client_ip(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    dry_run = bool((body or {}).get("dry_run"))

    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.runtime_ref.isnot(None))
        )).scalars().all()
        rows = [(a.id, a.account_id, a.slug, a.runtime_ref, a.volume_id) for a in agents]
        image_id = await _main_image_id(db)

    if dry_run:
        return {"ok": True, "dry_run": True,
                "machines": [{"agent": slug, "machine_id": ref, "has_volume": bool(vid)}
                             for (_id, _acct, slug, ref, vid) in rows]}

    if rows and not os.environ.get("FLY_API_TOKEN"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Fly API not configured")
    if rows and not image_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "No built main image to re-provision onto")

    from cloud.runtime.fly_machines import FlyMachinesRuntime
    fly = FlyMachinesRuntime()
    attached, skipped, errors = 0, 0, []
    for (agent_id, account_id, slug, ref, _vid) in rows:
        try:
            result = await _recreate_with_volume(fly, account_id, agent_id, ref, image_id)
            if result.get("skipped"):
                skipped += 1
            else:
                attached += 1
        except Exception as e:
            log.error("attach-volume failed for %s (%s): %s", slug, ref, e)
            errors.append({"machine_id": ref, "agent": slug, "error": str(e)})

    async with get_db_session() as db:
        await _audit(db, action="machine.volume_attach_all", actor=admin, actor_ip=ip,
                     metadata={"attached": attached, "skipped": skipped, "errors": len(errors)})
        await db.commit()
    return {"ok": True, "attached": attached, "skipped": skipped, "errors": errors}


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
