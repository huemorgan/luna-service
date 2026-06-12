"""Key pool resolution: agent-scoped → global, priority order, cooldown-aware."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import GatewayKey

# 401/403 likely means a revoked/bad key — long cooldown + needs admin attention.
AUTH_FAILURE_COOLDOWN = timedelta(hours=1)
# 429 is rate pressure — short cooldown, let the fallback absorb the burst.
RATE_LIMIT_COOLDOWN = timedelta(seconds=60)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite (tests) returns naive datetimes; Postgres returns aware. Normalize."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def resolve_keys(
    db: AsyncSession, service_slug: str, agent_id: uuid.UUID | None,
) -> list[GatewayKey]:
    """Usable keys for this request, most-preferred first.

    Agent-scoped overrides come before global keys; priority ascending within
    each scope; inactive and cooling-down keys are skipped.
    """
    now = datetime.now(timezone.utc)
    scopes = ["global"]
    if agent_id is not None:
        scopes.insert(0, f"agent:{agent_id}")

    out: list[GatewayKey] = []
    for scope in scopes:
        rows = (await db.execute(
            select(GatewayKey).where(
                GatewayKey.service_slug == service_slug,
                GatewayKey.scope == scope,
                GatewayKey.is_active.is_(True),
            ).order_by(GatewayKey.priority)
        )).scalars().all()
        out.extend(r for r in rows if _aware(r.cooldown_until) is None or _aware(r.cooldown_until) <= now)
    return out


async def mark_key_failure(db: AsyncSession, key_id: uuid.UUID, status_code: int) -> None:
    key = (await db.execute(
        select(GatewayKey).where(GatewayKey.id == key_id)
    )).scalar_one_or_none()
    if key is None:
        return
    delta = AUTH_FAILURE_COOLDOWN if status_code in (401, 403) else RATE_LIMIT_COOLDOWN
    key.cooldown_until = datetime.now(timezone.utc) + delta
    await db.flush()


async def mark_key_used(db: AsyncSession, key_id: uuid.UUID) -> None:
    key = (await db.execute(
        select(GatewayKey).where(GatewayKey.id == key_id)
    )).scalar_one_or_none()
    if key is None:
        return
    key.last_used_at = datetime.now(timezone.utc)
    await db.flush()
