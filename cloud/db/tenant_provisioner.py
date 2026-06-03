"""Creates Postgres schemas for new Luna tenants."""

from __future__ import annotations

import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

log = logging.getLogger(__name__)


def _safe_schema(slug: str) -> str:
    clean = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    return f"luna_user_{clean}"


async def provision_tenant_schema(db_url: str, schema_name: str) -> None:
    """Create a Postgres schema for a Luna tenant. Idempotent."""
    engine = create_async_engine(db_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :name"),
                {"name": schema_name},
            )
            if exists:
                log.info("Schema %s already exists", schema_name)
                return

            await conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            log.info("Created schema %s (vector + uuid-ossp extensions ensured)", schema_name)
    finally:
        await engine.dispose()


async def destroy_tenant_schema(db_url: str, schema_name: str) -> None:
    """Drop a tenant schema. For cleanup/testing only."""
    engine = create_async_engine(db_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            log.info("Dropped schema %s", schema_name)
    finally:
        await engine.dispose()
