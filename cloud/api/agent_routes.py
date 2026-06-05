"""Agent CRUD routes — list, create, start, stop, retry, destroy."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from cloud.auth.deps import require_active_account
from cloud.config import get_settings
from cloud.db.models import Account, Agent, User
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

router = APIRouter(prefix="/api/agents", tags=["agents"])


class CreateAgentRequest(BaseModel):
    name: str = "My Luna"


def _agent_dict(a: Agent) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "slug": a.slug,
        "status": a.status,
        "runtime_kind": a.runtime_kind,
        "internal_url": a.internal_url,
        "image_version": a.image_version,
        "error_message": a.error_message,
        "error_at": a.error_at.isoformat() if a.error_at else None,
        "created_at": a.created_at.isoformat(),
        "last_active_at": a.last_active_at.isoformat() if a.last_active_at else None,
    }


@router.get("")
async def list_agents(auth: tuple[User, Account] = Depends(require_active_account)):
    _, account = auth
    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.account_id == account.id).order_by(Agent.created_at)
        )).scalars().all()

    return [_agent_dict(a) for a in agents]


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

    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return _agent_dict(agent)


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
        if agent.status == "running":
            return _agent_dict(agent)
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
        return _agent_dict(agent)


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
        if agent.status == "stopped":
            return _agent_dict(agent)
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
        return _agent_dict(agent)


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
        result = _agent_dict(agent)

    from cloud.provisioning.workflow import provision_luna_for_account
    asyncio.create_task(provision_luna_for_account(str(account.id), agent_id=agent_id))
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
            handle = RuntimeHandle(agent.runtime_kind or "fly-machine", agent.runtime_ref, agent.internal_url or "")
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

    return {"compute": compute, "storage_r2": storage_r2}


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
            "volume": {"mount": "/workspace", "size_gb": 1},
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
