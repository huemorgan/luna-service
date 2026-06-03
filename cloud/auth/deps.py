"""FastAPI dependencies for auth — require_user, require_active_account."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from cloud.auth.session import get_session
from cloud.db.models import Account, Membership, User
from cloud.db.session import get_session as get_db_session


async def require_user(request: Request) -> User:
    sess = get_session(request)
    if not sess or "user_id" not in sess:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    async with get_db_session() as db:
        user = (await db.execute(
            select(User).where(User.id == uuid.UUID(sess["user_id"]))
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
        return user


async def require_active_account(request: Request) -> tuple[User, Account]:
    sess = get_session(request)
    if not sess or "user_id" not in sess or "account_id" not in sess:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    async with get_db_session() as db:
        user = (await db.execute(
            select(User).where(User.id == uuid.UUID(sess["user_id"]))
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

        membership = (await db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.account_id == uuid.UUID(sess["account_id"]),
                Membership.status == "active",
            )
        )).scalar_one_or_none()
        if not membership:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this account")

        account = (await db.execute(
            select(Account).where(Account.id == membership.account_id)
        )).scalar_one_or_none()
        if not account or account.status != "active":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account not active")

        return user, account
