"""Service API keys (plan 088) — generation, verification, scoped auth.

A ServiceApiKey lets a machine caller (typically a Luna agent holding the key
in its vault) use selected admin APIs without a session cookie. Scopes are
deliberately coarse — one checkbox in the admin UI per scope string.

Auth precedence in `require_admin_or_scope`: a presented API key is decisive —
a bad key is rejected even if a valid admin cookie rides along, so a leaked
key can never silently fall back to someone's session. No key → normal
`require_admin` cookie path.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, update

from cloud.auth.deps import require_admin
from cloud.db.models import ServiceApiKey, User
from cloud.db.session import get_session as get_db_session

KEY_SECRET_PREFIX = "lsk_"
KEY_PREFIX_LEN = 12  # display prefix, e.g. "lsk_ab12cd34"
LAST_USED_THROTTLE_S = 60.0

# Known scopes; the admin UI renders one checkbox per entry, in this order.
KNOWN_SCOPES: dict[str, str] = {
    "feedback:full": "Full feedback management",
}


def generate_key() -> tuple[str, str, str]:
    """Returns (secret, sha256_hash, display_prefix). Secret is shown once."""
    secret = KEY_SECRET_PREFIX + secrets.token_hex(20)
    return secret, hash_key(secret), secret[:KEY_PREFIX_LEN]


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite test engine drops tzinfo; normalize to UTC-aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def key_state(key: ServiceApiKey) -> str:
    if key.revoked_at is not None:
        return "revoked"
    exp = _aware(key.expires_at)
    if exp is not None and exp <= datetime.now(timezone.utc):
        return "expired"
    return "active"


def _presented_secret(request: Request) -> str | None:
    secret = request.headers.get("x-api-key")
    if not secret:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            candidate = auth[7:].strip()
            if candidate.startswith(KEY_SECRET_PREFIX):
                secret = candidate
    return secret or None


async def resolve_api_key(request: Request) -> ServiceApiKey | None:
    """Validate a presented key. None when no key is presented; 401 on a
    presented-but-invalid one (never fall through to cookie auth)."""
    secret = _presented_secret(request)
    if secret is None:
        return None
    presented_hash = hash_key(secret)
    async with get_db_session() as db:
        key = (await db.execute(
            select(ServiceApiKey).where(ServiceApiKey.key_hash == presented_hash)
        )).scalar_one_or_none()
        if key is None or not hmac.compare_digest(key.key_hash, presented_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        if key_state(key) != "active":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"API key {key_state(key)}")
        now = datetime.now(timezone.utc)
        last = _aware(key.last_used_at)
        if last is None or (now - last).total_seconds() > LAST_USED_THROTTLE_S:
            await db.execute(
                update(ServiceApiKey)
                .where(ServiceApiKey.id == key.id)
                .values(last_used_at=now)
            )
            await db.commit()
        db.expunge(key)
        return key


@dataclass
class AdminActor:
    """Who is acting on an admin API: a cookie admin, or a service key."""

    user: User | None = None
    api_key: ServiceApiKey | None = None

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user is not None else None

    @property
    def label(self) -> str:
        if self.api_key is not None:
            return f"api-key:{self.api_key.name}"
        return self.user.email if self.user else "unknown"


def require_admin_or_scope(scope: str):
    """Dependency factory: admin session cookie OR an active key with `scope`."""

    async def _dep(request: Request) -> AdminActor:
        key = await resolve_api_key(request)
        if key is not None:
            if scope not in (key.scopes or []):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, f"API key lacks scope '{scope}'"
                )
            return AdminActor(api_key=key)
        user = await require_admin(request)
        return AdminActor(user=user)

    return _dep
