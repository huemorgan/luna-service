"""Tenant token issue/verify. Raw tokens exist only at issue time."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import GatewayTenantToken

TOKEN_PREFIX = "lsv1-"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_tenant_token(credential: str) -> bool:
    return credential.startswith(TOKEN_PREFIX)


async def issue_token(db: AsyncSession, agent_id: uuid.UUID) -> str:
    """Issue a fresh token for an agent, revoking previous ones.

    Called at provision time; the raw value goes into the machine env and is
    never stored.
    """
    now = datetime.now(timezone.utc)
    existing = (await db.execute(
        select(GatewayTenantToken).where(
            GatewayTenantToken.agent_id == agent_id,
            GatewayTenantToken.revoked_at.is_(None),
        )
    )).scalars().all()
    for t in existing:
        t.revoked_at = now

    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    db.add(GatewayTenantToken(token_hash=_hash(raw), agent_id=agent_id))
    await db.flush()
    return raw


async def verify_token(db: AsyncSession, token: str) -> uuid.UUID | None:
    """Return the agent_id for a valid, unrevoked token; None otherwise."""
    if not is_tenant_token(token):
        return None
    row = (await db.execute(
        select(GatewayTenantToken).where(
            GatewayTenantToken.token_hash == _hash(token),
            GatewayTenantToken.revoked_at.is_(None),
        )
    )).scalar_one_or_none()
    return row.agent_id if row else None
