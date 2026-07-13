"""FastAPI dependencies for auth — require_user, require_active_account.

Plan 037-SPEED101: session→user/membership lookups run on every API request,
so they are cached in-process for AUTH_CACHE_TTL seconds. Cached rows are
expunged (detached, read-only); the rare route that mutates a user/account
queries its own fresh copy. Revocations (admin removed, membership revoked)
take up to AUTH_CACHE_TTL to propagate.
"""

from __future__ import annotations

import time
import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from cloud.auth.session import get_session
from cloud.db.models import Account, Membership, User
from cloud.db.session import get_session as get_db_session

AUTH_CACHE_TTL = 30.0

_user_cache: dict[str, tuple[float, User]] = {}
_account_cache: dict[tuple[str, str], tuple[float, Account]] = {}
_membership_cache: dict[tuple[str, str], float] = {}  # (user_id, account_id) → cached-at


def clear_auth_cache() -> None:
    """Test hook / manual invalidation."""
    _user_cache.clear()
    _account_cache.clear()
    _membership_cache.clear()


async def load_user_cached(user_id: str) -> User | None:
    now = time.monotonic()
    hit = _user_cache.get(user_id)
    if hit is not None and now - hit[0] < AUTH_CACHE_TTL:
        return hit[1]
    async with get_db_session() as db:
        user = (await db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )).scalar_one_or_none()
        if user is not None:
            db.expunge(user)
            _user_cache[user_id] = (now, user)
        else:
            _user_cache.pop(user_id, None)
        return user


async def check_membership_cached(user_id: str, account_id: str) -> bool:
    """Active-membership check; only positive results are cached."""
    now = time.monotonic()
    cached_at = _membership_cache.get((user_id, account_id))
    if cached_at is not None and now - cached_at < AUTH_CACHE_TTL:
        return True
    async with get_db_session() as db:
        membership = (await db.execute(
            select(Membership.id).where(
                Membership.user_id == uuid.UUID(user_id),
                Membership.account_id == uuid.UUID(account_id),
                Membership.status == "active",
            )
        )).scalar_one_or_none()
    if membership is not None:
        _membership_cache[(user_id, account_id)] = now
        return True
    return False


async def _load_active_account_cached(user_id: str, account_id: str) -> Account | None:
    now = time.monotonic()
    hit = _account_cache.get((user_id, account_id))
    if hit is not None and now - hit[0] < AUTH_CACHE_TTL:
        return hit[1]
    if not await check_membership_cached(user_id, account_id):
        return None
    async with get_db_session() as db:
        account = (await db.execute(
            select(Account).where(Account.id == uuid.UUID(account_id))
        )).scalar_one_or_none()
        if account is None or account.status != "active":
            return None
        db.expunge(account)
        _account_cache[(user_id, account_id)] = (now, account)
        return account


async def require_user(request: Request) -> User:
    sess = get_session(request)
    if not sess or "user_id" not in sess:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    user = await load_user_cached(sess["user_id"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


async def require_admin(request: Request) -> User:
    user = await require_user(request)
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


def _origin_of(url: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


async def enforce_same_origin(request: Request) -> None:
    """CSRF guard for cookie-authenticated mutation routes (039/002).

    Browsers always attach Origin (or at least Referer) to cross-site
    state-changing requests, so a present-but-foreign value is rejected.
    Requests with neither header (curl, tests, server-to-server) pass — they
    cannot be riding a victim's ambient cookie from a web page.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    claimed = request.headers.get("origin") or request.headers.get("referer")
    if not claimed:
        return
    from cloud.config import get_settings

    if _origin_of(claimed) != _origin_of(get_settings().base_url):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-origin request rejected")


async def require_active_account(request: Request) -> tuple[User, Account]:
    sess = get_session(request)
    if not sess or "user_id" not in sess or "account_id" not in sess:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    user = await load_user_cached(sess["user_id"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    account = await _load_active_account_cached(sess["user_id"], sess["account_id"])
    if account is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this account")

    return user, account
