"""Agent CRUD routes — list, create, start, stop, retry, destroy."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from cloud.auth.deps import require_active_account
from cloud.config import get_settings
from cloud.db.models import Account, Agent, LunaImage, User
from cloud.db.session import get_session as get_db_session
from cloud.storage.r2 import list_prefix_stats, r2_configured

log = logging.getLogger(__name__)

METRICS_CACHE_TTL = timedelta(seconds=60)

# Region code → friendly name. Add more as we expand.
FLY_REGIONS = {
    "sjc": "San Jose",
    "iad": "Ashburn",
    "ord": "Chicago",
    "lhr": "London",
    "fra": "Frankfurt",
    "sin": "Singapore",
    "syd": "Sydney",
    "nrt": "Tokyo",
    "gru": "São Paulo",
    "ams": "Amsterdam",
}


def _make_slug(name: str, account_slug: str) -> str:
    """Generate a URL-safe slug from agent name, prefixed with account slug."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "luna"
    return f"{account_slug}-{base}"


# Plan 038: vibrant card accent colors. New agents get a random one; agents
# with color=NULL fall back deterministically so existing cards stay stable.
AGENT_COLOR_PALETTE = [
    "#f59e0b",  # amber
    "#f97316",  # orange
    "#f43f5e",  # rose
    "#ec4899",  # pink
    "#d946ef",  # fuchsia
    "#8b5cf6",  # violet
    "#6366f1",  # indigo
    "#0ea5e9",  # sky
    "#06b6d4",  # cyan
    "#10b981",  # emerald
    "#84cc16",  # lime
    "#ef4444",  # red
]

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def random_agent_color() -> str:
    return random.choice(AGENT_COLOR_PALETTE)


def _fallback_color(agent_id: uuid.UUID) -> str:
    return AGENT_COLOR_PALETTE[int(agent_id.int) % len(AGENT_COLOR_PALETTE)]

router = APIRouter(prefix="/api/agents", tags=["agents"])


class CreateAgentRequest(BaseModel):
    name: str = "My Luna"


class UpdateAgentRequest(BaseModel):
    name: str | None = None
    color: str | None = None


async def _main_image_version(db) -> str | None:
    """Version of the current main (default) built image — what a machine
    upgrades *to*. ``None`` when no main image is set."""
    img = (await db.execute(
        select(LunaImage).where(
            LunaImage.is_main == True,  # noqa: E712
            LunaImage.build_status == "built",
        )
    )).scalar_one_or_none()
    return img.version if img else None


def _agent_dict(a: Agent, latest_version: str | None = None) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "slug": a.slug,
        "color": a.color or _fallback_color(a.id),
        "status": a.status,
        "runtime_kind": a.runtime_kind,
        "internal_url": a.internal_url,
        "image_version": a.image_version,
        "latest_version": latest_version,
        "upgrade_available": bool(
            latest_version and a.runtime_ref and a.image_version != latest_version
        ),
        "error_message": a.error_message,
        "error_at": a.error_at.isoformat() if a.error_at else None,
        "created_at": a.created_at.isoformat(),
        "last_active_at": a.last_active_at.isoformat() if a.last_active_at else None,
    }


async def _tenant_request(
    agent: Agent,
    method: str,
    path: str,
    json_body: dict | None = None,
    *,
    user_email: str,
    timeout: float = 25.0,
) -> tuple[int | None, dict | None]:
    """Call the tenant's Luna over the trusted-proxy channel.

    Authenticates as the machine owner (proxy secret + user header). Wakes the
    machine on a connection failure and retries once. Returns
    ``(status_code, json | None)``; ``(None, None)`` when unreachable. Never
    raises — callers degrade gracefully.
    """
    from cloud.api.proxy import _try_wake_agent
    from cloud.runtime.proxy_secret import derive_proxy_secret

    root_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")
    headers = {
        "x-luna-proxy-secret": derive_proxy_secret(root_secret, str(agent.id)),
        "x-luna-user": user_email,
        "content-type": "application/json",
    }
    if agent.runtime_ref:
        headers["fly-force-instance-id"] = agent.runtime_ref
    url = f"{(agent.internal_url or '').rstrip('/')}{path}"

    async def _send() -> tuple[int, dict | None]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10)) as client:
            resp = await client.request(method, url, headers=headers, json=json_body)
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                data = None
            return resp.status_code, data

    try:
        return await _send()
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
        if await _try_wake_agent(agent):
            try:
                return await _send()
            except Exception:  # noqa: BLE001
                return None, None
        return None, None
    except Exception:  # noqa: BLE001
        return None, None


@router.get("")
async def list_agents(auth: tuple[User, Account] = Depends(require_active_account)):
    _, account = auth
    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.account_id == account.id).order_by(Agent.created_at)
        )).scalars().all()
        latest = await _main_image_version(db)

    return [_agent_dict(a, latest) for a in agents]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: CreateAgentRequest,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    user, account = auth

    name = body.name.strip() or "My Luna"
    base_slug = _make_slug(name, account.slug)

    async with get_db_session() as db:
        slug = base_slug
        suffix = 1
        while (await db.execute(select(Agent).where(Agent.slug == slug))).scalar_one_or_none():
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        agent = Agent(
            account_id=account.id,
            creator_id=user.id,
            name=name,
            slug=slug,
            status="provisioning",
            color=random_agent_color(),
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        agent_id = str(agent.id)
        result = _agent_dict(agent)

    from cloud.provisioning.workflow import provision_luna_for_account
    asyncio.create_task(provision_luna_for_account(str(account.id), agent_id=agent_id))

    return result


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        latest = await _main_image_version(db) if agent else None

    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return _agent_dict(agent, latest)


@router.patch("/{agent_id}")
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    """Update display fields — name and/or card color. Slug, routing and storage stay stable."""
    _, account = auth
    if body.name is None and body.color is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")

    name = body.name.strip() if body.name is not None else None
    if body.name is not None:
        if not name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name cannot be empty")
        if len(name) > 100:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name too long (max 100 characters)")
    if body.color is not None and not _HEX_COLOR_RE.match(body.color):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Color must be #RRGGBB")

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        if name is not None:
            agent.name = name
        if body.color is not None:
            agent.color = body.color.lower()
        await db.commit()
        await db.refresh(agent)
        return _agent_dict(agent, await _main_image_version(db))


@router.post("/{agent_id}/start")
async def start_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        latest = await _main_image_version(db)
        if agent.status == "running":
            return _agent_dict(agent, latest)
        if not agent.runtime_ref:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Agent has no runtime to start")

        from cloud.provisioning.workflow import _get_runtime
        from cloud.runtime.base import RuntimeHandle
        runtime = _get_runtime()
        handle = RuntimeHandle(agent.runtime_kind or "fly-machine", agent.runtime_ref, agent.internal_url or "")
        try:
            await runtime.start(handle) if hasattr(runtime, 'start') else None
            agent.status = "running"
            agent.error_message = None
        except Exception as e:
            agent.status = "error"
            agent.error_message = str(e)
            agent.error_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(agent)
        return _agent_dict(agent, latest)


@router.post("/{agent_id}/stop")
async def stop_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        latest = await _main_image_version(db)
        if agent.status == "stopped":
            return _agent_dict(agent, latest)
        if not agent.runtime_ref:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Agent has no runtime to stop")

        from cloud.provisioning.workflow import _get_runtime
        from cloud.runtime.base import RuntimeHandle
        runtime = _get_runtime()
        handle = RuntimeHandle(agent.runtime_kind or "fly-machine", agent.runtime_ref, agent.internal_url or "")
        try:
            await runtime.stop(handle)
            agent.status = "stopped"
        except Exception as e:
            agent.status = "error"
            agent.error_message = str(e)
            agent.error_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(agent)
        return _agent_dict(agent, latest)


@router.post("/{agent_id}/retry")
async def retry_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

        agent.status = "provisioning"
        agent.error_message = None
        agent.error_at = None
        await db.commit()
        await db.refresh(agent)
        result = _agent_dict(agent, await _main_image_version(db))

    from cloud.provisioning.workflow import provision_luna_for_account
    asyncio.create_task(provision_luna_for_account(str(account.id), agent_id=agent_id))
    return result


@router.get("/{agent_id}/upgrade-check")
async def upgrade_check(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    """Pre-flight an upgrade: what's new + how the target image treats the
    machine's installed plugins (consumes Luna 0.17.002+ /api/plugins/upgrade-check).

    Always 200. ``upgradable:false`` when nothing to do. When the machine can't be
    pre-checked (asleep, unreachable, or on a pre-0.17 image), ``compat:"unavailable"``
    with release notes still shown so the user can upgrade with eyes open.
    """
    user, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        target = (await db.execute(
            select(LunaImage).where(
                LunaImage.is_main == True,  # noqa: E712
                LunaImage.build_status == "built",
            )
        )).scalar_one_or_none()

    if not target:
        return {"upgradable": False, "reason": "No newer image is available."}
    if not agent.runtime_ref:
        return {"upgradable": False, "reason": "This machine isn't provisioned yet."}
    if agent.image_version == target.version:
        return {"upgradable": False, "reason": "Already on the latest version."}

    base = {
        "upgradable": True,
        "current_version": agent.image_version,
        "target_version": target.version,
        "release_notes": target.release_notes,
    }
    if target.sdk_major is None or target.sdk_min_major is None:
        return {**base, "compat": "unavailable",
                "reason": "The target image didn't record compatibility data."}

    code, data = await _tenant_request(
        agent, "POST", "/api/plugins/upgrade-check",
        {
            "luna_version": target.version,
            "sdk_major": target.sdk_major,
            "sdk_min_major": target.sdk_min_major,
        },
        user_email=user.email,
    )
    if code == 200 and isinstance(data, dict):
        return {
            **base,
            "compat": "ok",
            "verdict": data.get("verdict"),
            "summary": data.get("summary"),
            "plugins": data.get("plugins", []),
        }
    if code == 404:
        return {**base, "compat": "unavailable",
                "reason": "This machine is on an older Luna that can't pre-check compatibility."}
    return {**base, "compat": "unavailable",
            "reason": "Couldn't reach the machine to check compatibility."}


class UpgradeRequest(BaseModel):
    mode: str = "upgrade_only"  # "upgrade_only" | "update_plugins_then_upgrade"


@router.post("/{agent_id}/upgrade")
async def upgrade_agent(
    agent_id: str,
    request: Request,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    """Upgrade this machine to the current main image (the latest version).

    User-facing counterpart of the admin per-machine image update — always
    targets the main image, scoped to the caller's account. With
    ``mode="update_plugins_then_upgrade"`` the machine's ``needs_upgrade`` plugins
    are bumped to a target-compatible version *before* the image swap.
    """
    user, account = auth
    try:
        body = UpgradeRequest(**(await request.json()))
    except Exception:  # noqa: BLE001 — empty/invalid body → defaults
        body = UpgradeRequest()

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        if not agent.runtime_ref:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Agent has no machine to upgrade")

        target = (await db.execute(
            select(LunaImage).where(
                LunaImage.is_main == True,  # noqa: E712
                LunaImage.build_status == "built",
            )
        )).scalar_one_or_none()
        if not target:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No image available to upgrade to")
        if agent.image_version == target.version:
            return _agent_dict(agent, target.version)
        runtime_ref = agent.runtime_ref
        target_tag = target.registry_tag
        target_version = target.version
        target_sdk_major = target.sdk_major
        target_sdk_min_major = target.sdk_min_major

    plugin_results: list[dict] = []
    if body.mode == "update_plugins_then_upgrade" and target_sdk_major is not None:
        code, data = await _tenant_request(
            agent, "POST", "/api/plugins/upgrade-check",
            {"luna_version": target_version, "sdk_major": target_sdk_major,
             "sdk_min_major": target_sdk_min_major},
            user_email=user.email,
        )
        plugins = (data or {}).get("plugins", []) if code == 200 else []
        for p in plugins:
            if p.get("status") != "needs_upgrade":
                continue
            name = p.get("name")
            mp_url = p.get("marketplace_url")
            if not mp_url:
                plugin_results.append({"name": name, "ok": False,
                                       "error": "marketplace_url unknown"})
                continue
            ucode, _ = await _tenant_request(
                agent, "POST", "/api/p/plugin-marketplace/upgrade",
                {"marketplace_url": mp_url, "name": name, "version": p.get("upgrade_to")},
                user_email=user.email,
            )
            plugin_results.append({"name": name, "ok": ucode == 200,
                                   "to": p.get("upgrade_to")})

    if not os.environ.get("FLY_API_TOKEN"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Fly API not configured")

    from cloud.runtime.fly_machines import FlyMachinesRuntime
    fly = FlyMachinesRuntime()
    try:
        await fly.update_machine_image(runtime_ref, target_tag)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to upgrade machine: {e}")

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.id == uuid.UUID(agent_id))
        )).scalar_one()
        agent.image_version = target_version
        await db.commit()
        await db.refresh(agent)
        result = _agent_dict(agent, target_version)
    if plugin_results:
        result["plugin_results"] = plugin_results
    return result


@router.delete("/{agent_id}")
async def destroy_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

        if agent.runtime_ref:
            from cloud.provisioning.workflow import _get_runtime
            from cloud.runtime.base import RuntimeHandle
            runtime = _get_runtime()
            handle = RuntimeHandle(
                agent.runtime_kind or "fly-machine",
                agent.runtime_ref,
                agent.internal_url or "",
                extra={"volume_id": agent.volume_id, "agent_slug": agent.slug},
            )
            try:
                await runtime.destroy(handle)
            except Exception as e:
                log.warning("Failed to destroy runtime for agent %s: %s", agent_id, e)

        await db.delete(agent)
        await db.commit()

    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Detail endpoint (phase 006 — agent detail page)
# ─────────────────────────────────────────────────────────────────────────────


def _fly_event_ts(events: list[dict], event_type: str) -> str | None:
    """Find the most recent Fly event of a given type and return its ISO ts."""
    for ev in events or []:
        if ev.get("type") == event_type or ev.get("status") == event_type:
            ts = ev.get("timestamp")
            if isinstance(ts, (int, float)):
                # Fly returns ms since epoch
                return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
            if isinstance(ts, str):
                return ts
    return None


async def _refresh_metrics(agent: Agent) -> dict:
    """Pull live Fly + R2 stats. Always returns a dict; never raises."""
    compute: dict = {"kind": agent.runtime_kind, "machine_id": agent.runtime_ref}
    storage_r2: dict = {"prefix": f"tenant/{agent.slug}/" if agent.slug else None}
    storage_files: dict | None = None

    # Fly machine describe — always construct a Fly client directly so we get
    # live data even when the deployment uses docker-local for *provisioning*
    # (e.g. an old agent record still pointing at a Fly machine).
    if agent.runtime_kind == "fly-machine" and agent.runtime_ref and os.environ.get("FLY_API_TOKEN"):
        try:
            from cloud.runtime.fly_machines import FlyMachinesRuntime
            fly = FlyMachinesRuntime()
            machine = await fly.describe(agent.runtime_ref)
            if machine is None:
                compute["state"] = "not_found"
                compute["error"] = "Machine not found on Fly"
            else:
                cfg = machine.get("config") or {}
                guest = cfg.get("guest") or {}
                compute.update({
                    "app": os.environ.get("FLY_APP", "luna-agents"),
                    "region": machine.get("region"),
                    "image": cfg.get("image"),
                    "size": {
                        "cpu_kind": guest.get("cpu_kind"),
                        "cpus": guest.get("cpus"),
                        "memory_mb": guest.get("memory_mb"),
                    },
                    "state": machine.get("state"),
                    "created_at": machine.get("created_at"),
                    "last_started_at": _fly_event_ts(machine.get("events") or [], "start"),
                })
                # Plan 025.5: live persistent-volume usage (durable files health).
                mounts = cfg.get("mounts") or []
                workspace = next((m for m in mounts if m.get("path") == "/workspace"), None)
                if workspace and machine.get("state") == "started":
                    usage = await fly.volume_usage(agent.runtime_ref)
                    storage_files = {
                        "backend": "fly",
                        "durable": True,
                        "location": "/workspace/files",
                        **(usage or {}),
                    }
        except Exception as exc:
            log.warning("Fly describe error for agent %s: %s", agent.id, exc)
            compute["state"] = "error"
            compute["error"] = str(exc)

    # R2 prefix stats
    if agent.slug:
        try:
            stats = await list_prefix_stats(f"tenant/{agent.slug}/")
            storage_r2.update(stats)
        except Exception as exc:
            log.warning("R2 stats error for agent %s: %s", agent.id, exc)
            storage_r2.update({"object_count": 0, "size_bytes": 0, "configured": False})
    else:
        storage_r2.update({"object_count": 0, "size_bytes": 0, "configured": r2_configured()})

    return {"compute": compute, "storage_r2": storage_r2, "storage_files": storage_files}


@router.get("/{agent_id}/details")
async def get_agent_details(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    """Detail-page payload: identity + routing + storage + live Fly compute.

    Fly + R2 lookups are cached on the agent row for METRICS_CACHE_TTL so the
    detail page is cheap to reload. Pass ?refresh=1 to bypass the cache.
    """
    _, account = auth
    settings = get_settings()

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

        creator = (await db.execute(
            select(User).where(User.id == agent.creator_id)
        )).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        cache_fresh = (
            agent.cached_metrics is not None
            and agent.cached_metrics_at is not None
            and (now - agent.cached_metrics_at) < METRICS_CACHE_TTL
        )

        if cache_fresh:
            metrics = agent.cached_metrics or {}
            cached_at = agent.cached_metrics_at
        else:
            metrics = await _refresh_metrics(agent)
            agent.cached_metrics = metrics
            agent.cached_metrics_at = now
            await db.commit()
            await db.refresh(agent)
            cached_at = agent.cached_metrics_at

    compute = dict(metrics.get("compute") or {})
    if compute.get("region"):
        compute["region_label"] = FLY_REGIONS.get(compute["region"], compute["region"])

    image_tag = compute.get("image", "")
    if image_tag:
        async with get_db_session() as db:
            luna_img = (await db.execute(
                select(LunaImage).where(LunaImage.registry_tag == image_tag)
            )).scalar_one_or_none()
            if luna_img:
                compute["image_version"] = luna_img.version
                compute["image_cache_warmed_at"] = luna_img.cache_warmed_at.isoformat() if luna_img.cache_warmed_at else None

    public_url = f"{settings.base_url.rstrip('/')}/a/{agent.slug}/" if agent.slug else None

    tenant_db_host = (
        os.environ.get("CLOUD_TENANT_DB_HOST")
        or _host_from_url(settings.tenant_database_url or settings.database_url)
    )

    return {
        "agent": _agent_dict(agent),
        "account": {
            "id": str(account.id),
            "slug": account.slug,
            "name": account.name,
            "plan": account.plan,
        },
        "creator": {
            "email": creator.email if creator else None,
            "name": creator.name if creator else None,
        },
        "routing": {
            "public_url": public_url,
            "internal_url": agent.internal_url,
            "slug": agent.slug,
        },
        "storage": {
            "postgres": {
                "host": tenant_db_host,
                "schema": agent.db_schema or (f"luna_user_{agent.slug.replace('-', '_')}" if agent.slug else None),
            },
            "r2": metrics.get("storage_r2") or {
                "prefix": f"tenant/{agent.slug}/" if agent.slug else None,
                "object_count": 0,
                "size_bytes": 0,
                "configured": r2_configured(),
            },
            "volume": {
                "mount": "/workspace",
                "volume_id": agent.volume_id,
                "region": agent.volume_region,
                "size_gb": agent.volume_size_gb,
                "durable": bool(agent.volume_id),
                "files": metrics.get("storage_files"),
            },
            "vault_key_ref": agent.vault_key_ref,
        },
        "compute": compute,
        "metrics_cached_at": cached_at.isoformat() if cached_at else None,
        "coming_soon": {
            "activity": [
                {"key": "messages_this_month", "label": "Messages this month", "phase": "008"},
                {"key": "tool_calls", "label": "Tool calls", "phase": "008"},
                {"key": "active_hours_per_day", "label": "Active hours / day", "phase": "008"},
            ],
            "spend": [
                {"key": "llm_cost", "label": "LLM cost this month", "phase": "008"},
                {"key": "compute_cost", "label": "Compute cost (Fly)", "phase": "008"},
                {"key": "storage_cost", "label": "Storage cost", "phase": "008"},
                {"key": "cost_per_plugin", "label": "Cost per plugin", "phase": "008"},
                {"key": "cost_cap", "label": "Cost cap", "phase": "009"},
            ],
        },
    }


def _host_from_url(url: str) -> str | None:
    """Extract host from a SQLAlchemy/Postgres URL for display."""
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        # SQLAlchemy URLs may have a driver prefix like postgresql+asyncpg://
        u = urlparse(url.replace("+asyncpg", "").replace("+psycopg", ""))
        return u.hostname
    except Exception:
        return None
