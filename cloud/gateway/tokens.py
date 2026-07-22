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


async def issue_token(db: AsyncSession, agent_id: uuid.UUID,
                      *, revoke_existing: bool = True) -> str:
    """Issue a fresh token for an agent.

    The raw value goes into the machine env and is never stored. With
    ``revoke_existing=False`` the agent's current tokens stay valid — use this
    when re-provisioning a RUNNING machine, then call ``revoke_other_tokens``
    only after the new token has actually been pushed. Revoking before the push
    lands leaves the machine with a dead token if the push fails.
    """
    if revoke_existing:
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


async def revoke_other_tokens(db: AsyncSession, agent_id: uuid.UUID, keep_raw: str) -> int:
    """Revoke every unrevoked token for the agent except ``keep_raw``.
    Call after ``keep_raw`` is confirmed live on the machine."""
    keep_hash = _hash(keep_raw)
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(GatewayTenantToken).where(
            GatewayTenantToken.agent_id == agent_id,
            GatewayTenantToken.revoked_at.is_(None),
        )
    )).scalars().all()
    revoked = 0
    for t in rows:
        if t.token_hash != keep_hash:
            t.revoked_at = now
            revoked += 1
    await db.flush()
    return revoked


async def revoke_raw_token(db: AsyncSession, raw: str) -> None:
    """Revoke one token by raw value — cleanup for a token that was issued but
    never delivered to a machine."""
    row = (await db.execute(
        select(GatewayTenantToken).where(
            GatewayTenantToken.token_hash == _hash(raw),
            GatewayTenantToken.revoked_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is not None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.flush()


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
