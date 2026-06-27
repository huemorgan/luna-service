"""Per-agent gateway guardrails (plan 026.1 §Guardrails).

Allow/deny + an optional request budget, stored on the agent
(``config_overrides["gateway"]``) and enforced at the proxy. Default = no policy
= allow everything (today's behaviour). A short TTL cache keeps the hot proxy
path from re-reading the agent row on every call.

    config_overrides["gateway"] = {
        "allow": ["browser-use", ...],     # if present, ONLY these are allowed
        "deny":  ["giphy", ...],            # explicitly blocked
        "monthly_request_cap": 10000,       # billable requests / 28 days
    }
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import Agent, UsageEvent

# 28 days = 4 whole weeks (project convention) for the "monthly" budget window.
_BUDGET_WINDOW = timedelta(days=28)
_TTL_SECONDS = 30.0
_CACHE: dict[uuid.UUID, tuple[float, dict]] = {}


def invalidate_policy_cache(agent_id: uuid.UUID | None = None) -> None:
    if agent_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(agent_id, None)


async def get_agent_policy(db: AsyncSession, agent_id: uuid.UUID) -> dict:
    now = time.monotonic()
    hit = _CACHE.get(agent_id)
    if hit and hit[0] > now:
        return hit[1]
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    policy = ((agent.config_overrides or {}).get("gateway") or {}) if agent else {}
    _CACHE[agent_id] = (now + _TTL_SECONDS, policy)
    return policy


async def deny_reason(
    db: AsyncSession, agent_id: uuid.UUID, service_slug: str,
) -> str | None:
    """Return a human reason to block this call, or None to allow."""
    policy = await get_agent_policy(db, agent_id)
    if not policy:
        return None

    allow = policy.get("allow")
    if allow and service_slug not in allow:
        return f"'{service_slug}' is not in this agent's allow list"
    if service_slug in (policy.get("deny") or []):
        return f"'{service_slug}' is denied for this agent"

    cap = policy.get("monthly_request_cap")
    if cap:
        since = datetime.now(timezone.utc) - _BUDGET_WINDOW
        used = (await db.execute(
            select(func.count()).select_from(UsageEvent).where(
                UsageEvent.agent_id == agent_id,
                UsageEvent.billable.is_(True),
                UsageEvent.created_at >= since,
            )
        )).scalar_one()
        if used >= cap:
            return f"monthly request cap reached ({cap})"
    return None
