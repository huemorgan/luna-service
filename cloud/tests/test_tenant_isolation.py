"""Plan 014 — tenant isolation unit tests.

- Proxy secret derivation (pure, always runs).
- URL composition helpers (pure, always runs).
- Provisioner SQL flow + real isolation enforcement against a throwaway
  Postgres, gated behind ISOLATION_PG_URL (a superuser/admin URL). Skipped
  when not set so CI without Postgres still passes.
"""

from __future__ import annotations

import os
import uuid

import pytest

from cloud.db.tenant_provisioner import (
    _safe_db_name,
    _swap_database,
    provision_tenant_database,
)
from cloud.provisioning.workflow import _compose_agent_db_url
from cloud.runtime.proxy_secret import derive_proxy_secret


# ── Pure helpers ────────────────────────────────────────────────────────────

def test_proxy_secret_deterministic_and_distinct():
    root = "root-secret"
    a = str(uuid.uuid4())
    b = str(uuid.uuid4())
    assert derive_proxy_secret(root, a) == derive_proxy_secret(root, a)
    assert derive_proxy_secret(root, a) != derive_proxy_secret(root, b)
    # different root → different secret
    assert derive_proxy_secret("other", a) != derive_proxy_secret(root, a)
    # hex, 64 chars (sha256)
    assert len(derive_proxy_secret(root, a)) == 64
    int(derive_proxy_secret(root, a), 16)  # parses as hex


def test_safe_db_name():
    assert _safe_db_name("vaselin-061") == "luna_a_vaselin_061"
    assert _safe_db_name("Roy.Moshe!") == "luna_a_roy_moshe_"


def test_swap_database():
    url = "postgresql+asyncpg://u:p@host/lunatenants"
    assert _swap_database(url, "luna_a_x") == "postgresql+asyncpg://u:p@host/luna_a_x"
    url_q = "postgresql+asyncpg://u:p@host/lunatenants?sslmode=require"
    assert _swap_database(url_q, "luna_a_x") == "postgresql+asyncpg://u:p@host/luna_a_x?sslmode=require"


def test_compose_agent_db_url_swaps_creds_and_db(monkeypatch):
    from cloud.db.tenant_provisioner import TenantDb
    monkeypatch.setenv("CLOUD_RUNTIME", "docker-local")
    admin = "postgresql+asyncpg://luna_tenant:masterpw@dpg-abc-a/lunatenants"
    td = TenantDb(db_name="luna_a_x", role="luna_a_x", password="newpw")
    out = _compose_agent_db_url(admin, td)
    assert "luna_a_x:newpw@" in out
    assert out.endswith("/luna_a_x")
    assert "luna_tenant" not in out
    assert "masterpw" not in out


def test_compose_agent_db_url_fly_host(monkeypatch):
    from cloud.db.tenant_provisioner import TenantDb
    monkeypatch.setenv("CLOUD_RUNTIME", "fly-machines")
    admin = "postgresql+asyncpg://luna_tenant:masterpw@dpg-abc-a/lunatenants"
    td = TenantDb(db_name="luna_a_x", role="luna_a_x", password="newpw")
    out = _compose_agent_db_url(admin, td)
    assert "@dpg-abc-a.oregon-postgres.render.com/luna_a_x" in out


# ── Real Postgres isolation (gated) ─────────────────────────────────────────

ADMIN_URL = os.environ.get("ISOLATION_PG_URL")
pg = pytest.mark.skipif(not ADMIN_URL, reason="set ISOLATION_PG_URL to run")


@pg
@pytest.mark.asyncio
async def test_provision_creates_isolated_db_and_enforces_access():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    slug_a = f"iso-test-a-{uuid.uuid4().hex[:8]}"
    slug_b = f"iso-test-b-{uuid.uuid4().hex[:8]}"

    a = await provision_tenant_database(ADMIN_URL, slug_a)
    b = await provision_tenant_database(ADMIN_URL, slug_b)

    host_db_a = _swap_database  # noqa: F841  (reuse helper conceptually)

    def _agent_url(td):
        import re
        u = re.sub(r"://[^@]+@", f"://{td.role}:{td.password}@", ADMIN_URL, count=1)
        return _swap_database(u, td.db_name)

    # A can connect to its own DB, create + drop a table, use vector.
    eng_a = create_async_engine(_agent_url(a), isolation_level="AUTOCOMMIT")
    try:
        async with eng_a.connect() as conn:
            await conn.execute(text("CREATE TABLE _probe (id int)"))
            await conn.execute(text("DROP TABLE _probe"))
            has_vec = await conn.scalar(text("SELECT 1 FROM pg_extension WHERE extname='vector'"))
            assert has_vec == 1
    finally:
        await eng_a.dispose()

    # A cannot connect to B's database.
    bad_url = _swap_database(
        __import__("re").sub(r"://[^@]+@", f"://{a.role}:{a.password}@", ADMIN_URL, count=1),
        b.db_name,
    )
    eng_bad = create_async_engine(bad_url, isolation_level="AUTOCOMMIT")
    with pytest.raises(Exception):
        async with eng_bad.connect() as conn:
            await conn.execute(text("SELECT 1"))
    await eng_bad.dispose()

    # Idempotent: re-provision rotates the password (old creds stop working).
    a2 = await provision_tenant_database(ADMIN_URL, slug_a)
    assert a2.db_name == a.db_name
    assert a2.password != a.password
    eng_old = create_async_engine(_agent_url(a), isolation_level="AUTOCOMMIT")
    with pytest.raises(Exception):
        async with eng_old.connect() as conn:
            await conn.execute(text("SELECT 1"))
    await eng_old.dispose()

    # Cleanup
    admin_eng = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin_eng.connect() as conn:
        for td in (a, b):
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{td.db_name}"'))
            await conn.execute(text(f'DROP ROLE IF EXISTS "{td.role}"'))
    await admin_eng.dispose()
