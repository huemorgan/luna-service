"""044 — TOS consent recording on the login upsert."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cloud.api.auth_routes import TOS_VERSION, _upsert_user_and_account
from cloud.auth.identity import UserInfo
from cloud.db.models import User

pytestmark = pytest.mark.asyncio


async def test_new_user_records_current_tos(db_session, _patch_db):
    info = UserInfo(sub="tos-sub", email="tos@example.com", name="T", avatar_url=None)
    user, _ = await _upsert_user_and_account(info)
    assert user.tos_version == TOS_VERSION
    assert user.tos_accepted_at is not None


async def test_existing_user_upgraded_to_current_tos(db_session, _patch_db):
    info = UserInfo(sub="tos-sub2", email="tos2@example.com", name="T", avatar_url=None)
    user, _ = await _upsert_user_and_account(info)

    # Simulate a user who accepted an older version.
    row = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    row.tos_version = "2020-01-01"
    old_stamp = row.tos_accepted_at
    await db_session.commit()

    user, _ = await _upsert_user_and_account(info)
    assert user.tos_version == TOS_VERSION
    assert user.tos_accepted_at != old_stamp


async def test_same_version_login_keeps_original_stamp(db_session, _patch_db):
    info = UserInfo(sub="tos-sub3", email="tos3@example.com", name="T", avatar_url=None)
    first, _ = await _upsert_user_and_account(info)
    stamp = first.tos_accepted_at
    again, _ = await _upsert_user_and_account(info)
    assert again.tos_accepted_at == stamp
