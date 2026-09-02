"""Auth routes — Google OAuth flow + stub flow + logout."""

from __future__ import annotations

import logging
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

log = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

_states: dict[str, str] = {}  # state → redirect_to (simple in-memory for MVP)

# 044: current Terms of Service version (its effective date). Every login
# path shows "By continuing you agree to the Terms" before the OAuth
# redirect, so a login under this version is recorded as acceptance. Bump
# when the published terms materially change.
TOS_VERSION = "2026-07-16"


def _get_identity_provider(settings: Settings):
    if settings.identity_provider == "google":
        return GoogleIdentityProvider(settings.google_client_id, settings.google_client_secret)
    return StubIdentityProvider()


_ALLOWED_DOMAINS = {"monday.com"}
_ALLOWED_EMAILS = {
    "vaselin@gmail.com",
    "dotanbahat@gmail.com",
    "dotanbahat@googlemail.com",
    "omryman@gmail.com",
}


def _enforce_email_allowlist(email: str) -> None:
    domain = email.split("@", 1)[-1].lower()
    if domain in _ALLOWED_DOMAINS or email.lower() in _ALLOWED_EMAILS:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-ups are currently restricted.")


# Account slugs map to `luna.com.ai/<slug>`. These words are owned by the
# marketing site / app (plan 021) and must never become an account slug, or a
# user's Luna would be shadowed by a static page.
RESERVED_SLUGS = frozenset({
    "", "user", "api", "auth", "admin", "dashboard", "healthz", "proxy", "a",
    "assets", "favicon", "icons", "static", "robots", "sitemap",
    "products", "product", "pricing", "security", "about", "oss", "open-source",
    "hosting", "marketplace", "marketplaces", "login", "signup", "sign-up",
    "docs", "blog", "legal", "terms", "privacy", "support", "contact", "status",
})


def _make_slug(email: str) -> str:
    local = email.split("@")[0]
    slug = re.sub(r"[^a-z0-9]", "-", local.lower()).strip("-")
    if not slug or slug in RESERVED_SLUGS:
        return f"{slug or 'user'}-1"
    return slug


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
            if user.tos_version != TOS_VERSION:
                user.tos_version = TOS_VERSION
                user.tos_accepted_at = datetime.now(timezone.utc)
            await db.flush()
        else:
            user = User(
                google_sub=info.sub,
                email=info.email,
                name=info.name,
                avatar_url=info.avatar_url,
                last_login_at=datetime.now(timezone.utc),
                tos_version=TOS_VERSION,
                tos_accepted_at=datetime.now(timezone.utc),
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

            # 039/002: billing account + commercial pricing assignment are
            # created in the same transaction as the account itself, so no
            # authorized account is ever unassigned.
            from cloud.billing.assignments import AssignmentError, assign_new_account
            try:
                await assign_new_account(db, account.id)
                # 039/005: the one-time trial gift (amount/expiry from the
                # assigned version's config.trial) lands in the same
                # transaction — exactly once under concurrent callbacks.
                from cloud.billing.grants import grant_trial_gift
                await grant_trial_gift(db, account.id, email=info.email)
            except AssignmentError as exc:
                # Signup must not fail on an unseeded environment; billing
                # stays off for the account until versions exist.
                log.warning("No pricing assignment for new account %s: %s", account.id, exc)
            except Exception as exc:  # noqa: BLE001 — no gift beats a failed signup
                log.warning("No trial gift for new account %s: %s", account.id, exc)

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
            "is_admin": user.is_admin,
        },
        "account": {
            "id": str(account.id),
            "slug": account.slug,
            "name": account.name,
            "plan": account.plan,
        } if account else None,
    }
