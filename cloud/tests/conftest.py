"""Test fixtures — in-process FastAPI app with async SQLite."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import String, Text as SAText
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.types import JSON

from cloud.config import Settings
from cloud.db.models import Base, User, Account, Membership, Agent, LunaImage

# Register SQLite-compatible compilation for Postgres types
from sqlalchemy.ext.compiler import compiles


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


# ── Test settings ────────────────────────────────────────────────────────────

TEST_SETTINGS = Settings(
    env="test",
    database_url="sqlite+aiosqlite:///:memory:",
    session_secret="test-secret",
    identity_provider="stub",
    admin_webhook_secret="test-webhook-secret",
    github_pat="",
)


@pytest.fixture(autouse=True)
def _patch_settings():
    with patch("cloud.config.get_settings", return_value=TEST_SETTINGS):
        yield


@pytest.fixture(autouse=True)
def _reset_catalog_cache():
    """Plan 018: the model catalog has a process-local TTL cache; reset it around
    every test so a seeded catalog from one test never leaks into another."""
    from cloud.provisioning.model_catalog import invalidate_catalog_cache
    invalidate_catalog_cache()
    yield
    invalidate_catalog_cache()


# ── Database ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def _patch_db(db_engine):
    """Patch the session module to use the test engine."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _test_session():
        async with factory() as session:
            yield session

    with (
        patch("cloud.db.session._get_engine", return_value=db_engine),
        patch("cloud.db.session.get_session_factory", return_value=factory),
        patch("cloud.db.session.get_session", _test_session),
        patch("cloud.auth.deps.get_db_session", _test_session),
        patch("cloud.api.admin_routes.get_db_session", _test_session),
        patch("cloud.api.auth_routes.get_db_session", _test_session),
        patch("cloud.api.agent_routes.get_db_session", _test_session),
        patch("cloud.api.proxy.get_db_session", _test_session),
        patch("cloud.api.relay_routes.get_db_session", _test_session),
        patch("cloud.relay.forwarder.get_db_session", _test_session),
    ):
        yield


# ── Seed data ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession):
    user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        google_sub="admin-sub",
        email="vaselin@gmail.com",
        name="Admin",
        is_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def regular_user(db_session: AsyncSession):
    user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        google_sub="regular-sub",
        email="regular@example.com",
        name="Regular",
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def account(db_session: AsyncSession, admin_user: User):
    acc = Account(
        id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        slug="test-account",
        name="Test Account",
        created_by=admin_user.id,
    )
    db_session.add(acc)
    await db_session.flush()
    db_session.add(Membership(account_id=acc.id, user_id=admin_user.id, role="owner"))
    await db_session.commit()
    await db_session.refresh(acc)
    return acc


@pytest_asyncio.fixture
async def sample_agent(db_session: AsyncSession, admin_user: User, account: Account):
    agent = Agent(
        id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
        account_id=account.id,
        creator_id=admin_user.id,
        name="Test Agent",
        slug="test-account-test-agent",
        status="running",
        runtime_kind="fly-machine",
        runtime_ref="machine-123",
        internal_url="https://luna-agents.fly.dev",
        image_version="0.01.001",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest_asyncio.fixture
async def sample_image(db_session: AsyncSession, admin_user: User):
    img = LunaImage(
        id=uuid.UUID("00000000-0000-0000-0000-000000000030"),
        version="0.01.001",
        registry_tag="registry.fly.io/luna-tenants-prod:0.01.001",
        is_main=True,
        build_status="built",
        built_at=datetime.now(timezone.utc),
        created_by=admin_user.id,
    )
    db_session.add(img)
    await db_session.commit()
    await db_session.refresh(img)
    return img


# ── HTTP client ──────────────────────────────────────────────────────────────

def _make_session_cookie(user_id: str, account_id: str = "00000000-0000-0000-0000-000000000010") -> str:
    serializer = URLSafeTimedSerializer(TEST_SETTINGS.session_secret)
    payload = json.dumps({"user_id": user_id, "account_id": account_id})
    return serializer.dumps(payload)


@pytest_asyncio.fixture
async def admin_client(_patch_db, admin_user: User):
    from cloud.main import create_app
    app = create_app()
    cookie = _make_session_cookie(str(admin_user.id))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies={"luna_session": cookie}) as client:
        yield client


@pytest_asyncio.fixture
async def regular_client(_patch_db, regular_user: User):
    from cloud.main import create_app
    app = create_app()
    cookie = _make_session_cookie(str(regular_user.id))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies={"luna_session": cookie}) as client:
        yield client


@pytest_asyncio.fixture
async def anon_client(_patch_db):
    from cloud.main import create_app
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
