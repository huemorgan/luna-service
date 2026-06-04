"""Auth routes — Google OAuth flow + stub flow + logout."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from cloud.auth.deps import require_user
from cloud.auth.identity import GoogleIdentityProvider, StubIdentityProvider, UserInfo
from cloud.auth.session import clear_session, set_session
from cloud.config import Settings, get_settings
from cloud.db.models import Account, Membership, User
from cloud.db.session import get_session as get_db_session

router = APIRouter(tags=["auth"])

_states: dict[str, str] = {}  # state → redirect_to (simple in-memory for MVP)


def _get_identity_provider(settings: Settings):
    if settings.identity_provider == "google":
        return GoogleIdentityProvider(settings.google_client_id, settings.google_client_secret)
    return StubIdentityProvider()


_ALLOWED_DOMAINS = {"monday.com"}
_ALLOWED_EMAILS = {"vaselin@gmail.com"}


def _enforce_email_allowlist(email: str) -> None:
    domain = email.split("@", 1)[-1].lower()
    if domain in _ALLOWED_DOMAINS or email.lower() in _ALLOWED_EMAILS:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-ups are currently restricted.")


def _make_slug(email: str) -> str:
    local = email.split("@")[0]
    slug = re.sub(r"[^a-z0-9]", "-", local.lower()).strip("-")
    return slug or "user"


@router.get("/auth/mode")
async def auth_mode():
    settings = get_settings()
    return {"mode": settings.identity_provider}


@router.get("/auth/login")
async def login(request: Request):
    settings = get_settings()
    provider = _get_identity_provider(settings)
    state = secrets.token_urlsafe(32)
    _states[state] = str(request.query_params.get("next", "/dashboard"))
    url = await provider.get_authorization_url(settings.google_redirect_uri, state)
    return RedirectResponse(url, status_code=302)


@router.get("/auth/google/callback")
async def google_callback(code: str, state: str):
    redirect_to = _states.pop(state, "/dashboard")
    settings = get_settings()
    provider = _get_identity_provider(settings)

    try:
        user_info = await provider.exchange_code(code, settings.google_redirect_uri)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"OAuth exchange failed: {e}")

    _enforce_email_allowlist(user_info.email)
    user, account = await _upsert_user_and_account(user_info)

    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, str(user.id), str(account.id))
    return response


async def _upsert_user_and_account(info: UserInfo) -> tuple[User, Account]:
    async with get_db_session() as db:
        user = (await db.execute(
            select(User).where(User.google_sub == info.sub)
        )).scalar_one_or_none()

        if user:
            user.last_login_at = datetime.now(timezone.utc)
            if info.name:
                user.name = info.name
            if info.avatar_url:
                user.avatar_url = info.avatar_url
            await db.flush()
        else:
            user = User(
                google_sub=info.sub,
                email=info.email,
                name=info.name,
                avatar_url=info.avatar_url,
                last_login_at=datetime.now(timezone.utc),
            )
            db.add(user)
            await db.flush()

        membership = (await db.execute(
            select(Membership).where(Membership.user_id == user.id, Membership.status == "active")
        )).scalars().first()

        if membership:
            account = (await db.execute(
                select(Account).where(Account.id == membership.account_id)
            )).scalar_one()
        else:
            base_slug = _make_slug(info.email)
            slug = base_slug
            suffix = 1
            while (await db.execute(select(Account).where(Account.slug == slug))).scalar_one_or_none():
                slug = f"{base_slug}-{suffix}"
                suffix += 1

            account = Account(
                slug=slug,
                name=info.name or info.email.split("@")[0],
                created_by=user.id,
            )
            db.add(account)
            await db.flush()

            db.add(Membership(account_id=account.id, user_id=user.id, role="owner"))

        await db.commit()
        await db.refresh(user)
        await db.refresh(account)
        return user, account


@router.get("/auth/logout")
async def logout():
    response = RedirectResponse("/", status_code=302)
    clear_session(response)
    return response


@router.get("/api/auth/me")
async def me(user: User = Depends(require_user)):
    async with get_db_session() as db:
        membership = (await db.execute(
            select(Membership).where(Membership.user_id == user.id, Membership.status == "active")
        )).scalars().first()

        account = None
        if membership:
            account = (await db.execute(
                select(Account).where(Account.id == membership.account_id)
            )).scalar_one_or_none()

    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "avatar_url": user.avatar_url,
        },
        "account": {
            "id": str(account.id),
            "slug": account.slug,
            "name": account.name,
            "plan": account.plan,
        } if account else None,
    }
