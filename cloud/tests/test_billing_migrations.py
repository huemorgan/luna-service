"""039/001 — Alembic chain + Postgres enforcement triggers.

Runs only against the local docker Postgres (localhost:5435); skipped when it
is not reachable. Each test uses its own scratch database.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from unittest.mock import patch

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cloud.db import migrate
from cloud.db.migrate import _alembic_config, _expected_core_columns, _fingerprint_errors

PG_HOST, PG_PORT = "localhost", 5435
PG_BASE = f"postgresql+asyncpg://luna:luna@{PG_HOST}:{PG_PORT}"


def _pg_available() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="local Postgres (5435) not running")


async def _admin_exec(*statements: str) -> None:
    engine = create_async_engine(f"{PG_BASE}/postgres", isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            for stmt in statements:
                await conn.execute(text(stmt))
    finally:
        await engine.dispose()


async def _exec(url: str, *statements: str) -> list:
    engine = create_async_engine(url)
    results = []
    try:
        async with engine.begin() as conn:
            for stmt in statements:
                results.append(await conn.execute(text(stmt)))
        return results
    finally:
        await engine.dispose()


async def _table_columns(url: str) -> dict[str, set[str]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            def _read(sync_conn):
                insp = inspect(sync_conn)
                return {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names()}
            return await conn.run_sync(_read)
    finally:
        await engine.dispose()


@pytest.fixture
def scratch_db(monkeypatch):
    name = f"mig_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_admin_exec(f'CREATE DATABASE "{name}"'))
    url = f"{PG_BASE}/{name}"
    # alembic/env.py prefers CLOUD_DATABASE_URL; the conftest autouse fixture
    # sets it to SQLite, which would hijack the migration run.
    monkeypatch.setenv("CLOUD_DATABASE_URL", url)
    yield url
    asyncio.run(_admin_exec(f'DROP DATABASE IF EXISTS "{name}" (FORCE)'))


def _run_migrate(url: str) -> int:
    settings = type("S", (), {"database_url": url})()
    with patch.object(migrate, "get_settings", return_value=settings):
        return migrate.main()


def test_fresh_db_reaches_head(scratch_db):
    assert _run_migrate(scratch_db) == 0
    tables = asyncio.run(_table_columns(scratch_db))
    assert "credit_ledger_transactions" in tables
    assert "billing_outbox" in tables
    assert "users" in tables
    version = asyncio.run(_exec(scratch_db, "SELECT version_num FROM alembic_version"))
    assert version[0].scalar_one() == "0002"
    # Idempotent rerun.
    assert _run_migrate(scratch_db) == 0


def test_pre_alembic_db_is_stamped_and_upgraded(scratch_db):
    # Simulate production: baseline schema present, no alembic_version, with
    # the known drift (nullable is_admin, stray extra column).
    command.upgrade(_alembic_config(scratch_db), "0001")
    asyncio.run(_exec(
        scratch_db,
        "DROP TABLE alembic_version",
        "ALTER TABLE users ALTER COLUMN is_admin DROP NOT NULL",
        "ALTER TABLE agents ADD COLUMN legacy_extra text",
    ))
    assert _run_migrate(scratch_db) == 0
    version = asyncio.run(_exec(scratch_db, "SELECT version_num FROM alembic_version"))
    assert version[0].scalar_one() == "0002"
    tables = asyncio.run(_table_columns(scratch_db))
    assert "credit_grants" in tables


def test_fresh_and_stamped_paths_produce_identical_billing_schema(scratch_db, monkeypatch):
    fresh_name = f"mig_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_admin_exec(f'CREATE DATABASE "{fresh_name}"'))
    fresh_url = f"{PG_BASE}/{fresh_name}"
    try:
        # env.py prefers CLOUD_DATABASE_URL, so point it at each target in turn.
        monkeypatch.setenv("CLOUD_DATABASE_URL", fresh_url)
        command.upgrade(_alembic_config(fresh_url), "head")
        monkeypatch.setenv("CLOUD_DATABASE_URL", scratch_db)
        command.upgrade(_alembic_config(scratch_db), "0001")
        asyncio.run(_exec(scratch_db, "DROP TABLE alembic_version"))
        assert _run_migrate(scratch_db) == 0
        fresh = asyncio.run(_table_columns(fresh_url))
        stamped = asyncio.run(_table_columns(scratch_db))
        assert fresh == stamped
    finally:
        asyncio.run(_admin_exec(f'DROP DATABASE IF EXISTS "{fresh_name}" (FORCE)'))


def test_unknown_schema_refused(scratch_db):
    asyncio.run(_exec(scratch_db, "CREATE TABLE users (id uuid primary key)"))
    assert _run_migrate(scratch_db) == 1
    tables = asyncio.run(_table_columns(scratch_db))
    assert "alembic_version" not in tables  # refused without writing anything


def test_fingerprint_helper_units():
    expected = _expected_core_columns()
    assert set(expected) == migrate.CORE_TABLES
    ok = {t: set(cols) for t, cols in expected.items()}
    assert _fingerprint_errors(ok, expected) == []
    broken = {t: set(cols) for t, cols in expected.items() if t != "usage_events"}
    broken["users"] = broken["users"] - {"is_admin"}
    errors = _fingerprint_errors(broken, expected)
    assert any("usage_events" in e for e in errors)
    assert any("is_admin" in e for e in errors)


def test_triggers_enforce_ledger_invariants(scratch_db):
    assert _run_migrate(scratch_db) == 0
    account_id = "00000000-0000-0000-0000-000000000002"
    asyncio.run(_exec(
        scratch_db,
        "INSERT INTO users (id, google_sub, email, created_at, is_admin) "
        "VALUES ('00000000-0000-0000-0000-000000000001','sub','t@t.t',now(),false)",
        f"INSERT INTO accounts (id, slug, name, plan, status, created_by, created_at) "
        f"VALUES ('{account_id}','t','T','free','active',"
        f"'00000000-0000-0000-0000-000000000001',now())",
        f"INSERT INTO billing_accounts (account_id, billing_status, overrun_cap_credits, "
        f"created_at, updated_at) VALUES ('{account_id}','trial',1000,now(),now())",
    ))

    def txn_sql(txn_id: str, key: str) -> str:
        return (
            "INSERT INTO credit_ledger_transactions (id, type, idempotency_key, "
            f"request_hash, account_id, created_at) VALUES ('{txn_id}','grant','{key}','h',"
            f"'{account_id}',now())"
        )

    # Header with no postings → rejected at commit.
    with pytest.raises(Exception, match="no postings"):
        asyncio.run(_exec(scratch_db, txn_sql("00000000-0000-0000-0000-00000000000a", "t1")))

    # Unbalanced postings → rejected at commit.
    with pytest.raises(Exception, match="not zero"):
        asyncio.run(_exec(
            scratch_db,
            txn_sql("00000000-0000-0000-0000-00000000000b", "t2"),
            "INSERT INTO credit_ledger_postings (id, transaction_id, ledger_account, "
            "account_id, credits, created_at) VALUES (gen_random_uuid(),"
            f"'00000000-0000-0000-0000-00000000000b','customer_wallet','{account_id}',100,now())",
        ))

    # Balanced transaction commits.
    asyncio.run(_exec(
        scratch_db,
        txn_sql("00000000-0000-0000-0000-00000000000c", "t3"),
        "INSERT INTO credit_ledger_postings (id, transaction_id, ledger_account, "
        "account_id, credits, created_at) VALUES "
        f"(gen_random_uuid(),'00000000-0000-0000-0000-00000000000c','customer_wallet','{account_id}',100,now()),"
        f"(gen_random_uuid(),'00000000-0000-0000-0000-00000000000c','grant_issuance:gift','{account_id}',-100,now())",
    ))

    # Posted rows are immutable.
    with pytest.raises(Exception, match="immutable"):
        asyncio.run(_exec(
            scratch_db,
            "UPDATE credit_ledger_transactions SET reason='x' "
            "WHERE id='00000000-0000-0000-0000-00000000000c'",
        ))
    with pytest.raises(Exception, match="immutable"):
        asyncio.run(_exec(
            scratch_db,
            "DELETE FROM credit_ledger_postings "
            "WHERE transaction_id='00000000-0000-0000-0000-00000000000c'",
        ))


def test_triggers_enforce_version_immutability(scratch_db):
    assert _run_migrate(scratch_db) == 0
    vid = "00000000-0000-0000-0000-0000000000aa"
    asyncio.run(_exec(
        scratch_db,
        f"INSERT INTO commercial_pricing_versions (id, version_number, name, status, "
        f"config_json, config_schema_version, config_hash, created_at) "
        f"VALUES ('{vid}', 1, 'v1', 'draft', '{{}}'::jsonb, 1, 'hash1', now())",
    ))
    # Drafts are editable, and publishing is allowed.
    asyncio.run(_exec(
        scratch_db,
        f"UPDATE commercial_pricing_versions SET status='published', published_at=now() "
        f"WHERE id='{vid}'",
    ))
    # Published financial fields are frozen.
    with pytest.raises(Exception, match="immutable"):
        asyncio.run(_exec(
            scratch_db,
            f"UPDATE commercial_pricing_versions SET config_hash='tampered' WHERE id='{vid}'",
        ))
    with pytest.raises(Exception, match="cannot be deleted"):
        asyncio.run(_exec(scratch_db, f"DELETE FROM commercial_pricing_versions WHERE id='{vid}'"))
    # published → retired is the one allowed transition.
    asyncio.run(_exec(
        scratch_db,
        f"UPDATE commercial_pricing_versions SET status='retired' WHERE id='{vid}'",
    ))
    with pytest.raises(Exception, match="immutable"):
        asyncio.run(_exec(
            scratch_db,
            f"UPDATE commercial_pricing_versions SET status='draft' WHERE id='{vid}'",
        ))
