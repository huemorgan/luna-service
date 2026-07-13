"""Run database migrations before app startup (plan 039/001).

Usage: python -m cloud.db.migrate  (the container CMD runs this before uvicorn).

Handles three database states:
- already under Alembic (alembic_version exists) → upgrade to head;
- empty → upgrade to head (baseline runs for real);
- pre-Alembic production shape (tables created by the old startup DDL) →
  fingerprint-check the core schema, stamp the 0001 baseline, upgrade to head.

The fingerprint check compares table and column EXISTENCE against the ORM
core models, not nullability or defaults — production accumulated columns via
ad-hoc ALTERs (e.g. users.is_admin may be nullable there) and those
differences are harmless to the billing migration. Extra columns in the
database are tolerated with a warning; a missing table or column aborts with
exit code 1 and no writes, because stamping over an unknown schema could
corrupt the migration history.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cloud.config import get_settings
from cloud.db.models import Base

CLOUD_DIR = Path(__file__).resolve().parent.parent

# Tables the 0001 baseline owns. Must match CORE_TABLES in alembic/env.py.
CORE_TABLES = {
    "users", "accounts", "memberships", "agents", "luna_images",
    "gateway_services", "plugin_catalog", "gateway_models", "gateway_keys",
    "gateway_tenant_tokens", "usage_events", "composio_account_links",
    "relay_deliveries", "audit_log", "app_settings",
}

BASELINE_REVISION = "0001"

# Columns that post-0001 migrations add to core tables. The fingerprint
# compares a pre-Alembic database against the 0001 BASELINE shape, and the
# ORM models describe head — so anything added later must be excluded here,
# or every legacy database gets refused for lacking it. Grows with each
# migration that touches a CORE_TABLES table.
POST_BASELINE_COLUMNS: dict[str, set[str]] = {
    "agents": {"deleted_at"},  # 0004
}


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(CLOUD_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CLOUD_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _expected_core_columns() -> dict[str, set[str]]:
    return {
        name: {c.name for c in table.columns} - POST_BASELINE_COLUMNS.get(name, set())
        for name, table in Base.metadata.tables.items()
        if name in CORE_TABLES
    }


def _fingerprint_errors(
    existing: dict[str, set[str]], expected: dict[str, set[str]]
) -> list[str]:
    errors: list[str] = []
    for table, columns in sorted(expected.items()):
        if table not in existing:
            errors.append(f"missing table: {table}")
            continue
        missing = columns - existing[table]
        if missing:
            errors.append(f"table {table} missing columns: {sorted(missing)}")
        extra = existing[table] - columns
        if extra:
            print(f"[migrate] note: table {table} has extra columns {sorted(extra)} (tolerated)")
    return errors


async def _inspect_database(database_url: str) -> tuple[bool, dict[str, set[str]]]:
    """Return (alembic_version exists, {table: column names} for public tables)."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            def _read(sync_conn):
                insp = inspect(sync_conn)
                tables = insp.get_table_names()
                return (
                    "alembic_version" in tables,
                    {
                        t: {c["name"] for c in insp.get_columns(t)}
                        for t in tables
                        if t != "alembic_version"
                    },
                )
            return await conn.run_sync(_read)
    finally:
        await engine.dispose()


async def _current_stamp(database_url: str) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            row = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return row.scalar_one_or_none()
    finally:
        await engine.dispose()


def main() -> int:
    settings = get_settings()
    database_url = settings.database_url
    cfg = _alembic_config(database_url)

    versioned, existing = asyncio.run(_inspect_database(database_url))

    if versioned:
        stamp = asyncio.run(_current_stamp(database_url))
        print(f"[migrate] database at revision {stamp}; upgrading to head")
        command.upgrade(cfg, "head")
        return 0

    if not existing:
        print("[migrate] empty database; running all migrations")
        command.upgrade(cfg, "head")
        return 0

    print("[migrate] pre-Alembic database detected; fingerprinting core schema")
    errors = _fingerprint_errors(existing, _expected_core_columns())
    if errors:
        print("[migrate] REFUSING to stamp: schema does not match the 0001 baseline:")
        for err in errors:
            print(f"[migrate]   {err}")
        print("[migrate] resolve the schema drift manually, then rerun")
        return 1

    print(f"[migrate] fingerprint OK; stamping {BASELINE_REVISION} and upgrading to head")
    command.stamp(cfg, BASELINE_REVISION)
    command.upgrade(cfg, "head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
