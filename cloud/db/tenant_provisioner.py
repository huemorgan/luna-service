"""Provisions isolated Postgres for Luna tenants.

Plan 014 — hard tenant isolation. Each agent gets its **own database** and its
**own login role** on the shared Postgres instance. The agent's connection
string can reach only that one database; it cannot connect to other tenants'
databases or the control/shared database. Isolation is enforced by Postgres
credentials, never by asking the Luna image to behave.

The legacy `provision_tenant_schema` (one shared DB, schema-per-tenant) is kept
only for backwards compatibility with older tests; it is no longer used by the
provisioning workflow.
"""

from __future__ import annotations

import logging
import re
import secrets
import string
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

log = logging.getLogger(__name__)

_PW_ALPHABET = string.ascii_letters + string.digits


def _safe_schema(slug: str) -> str:
    clean = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    return f"luna_user_{clean}"


def _safe_db_name(slug: str) -> str:
    """Database + role name for an agent. Stable for a given slug."""
    clean = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    return f"luna_a_{clean}"


def _gen_password(n: int = 32) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(n))


@dataclass
class TenantDb:
    db_name: str
    role: str
    password: str


def _swap_database(url: str, db_name: str) -> str:
    """Return `url` with its database path replaced by `db_name`."""
    return re.sub(r"/[^/?]+(\?|$)", f"/{db_name}\\1", url, count=1)


def _admin_role(url: str) -> str:
    m = re.search(r"://([^:/?]+)", url)
    return m.group(1) if m else "postgres"


# Plan 071/073: per-role connection guardrails on the shared tenant cluster.
ROLE_CONNECTION_LIMIT = 12
ROLE_SETTINGS: dict[str, str] = {
    "idle_session_timeout": "'5min'",
    "idle_in_transaction_session_timeout": "'5min'",
    "tcp_keepalives_idle": "30",
    "tcp_keepalives_interval": "10",
    "tcp_keepalives_count": "3",
}


def role_settings_sql(role: str) -> list[str]:
    """ALTER ROLE statements applied to every tenant role (new or existing)."""
    out = [f'ALTER ROLE "{role}" CONNECTION LIMIT {ROLE_CONNECTION_LIMIT}']
    out += [f'ALTER ROLE "{role}" SET {k} = {v}' for k, v in ROLE_SETTINGS.items()]
    return out


async def provision_tenant_database(admin_db_url: str, agent_slug: str) -> TenantDb:
    """Create (or refresh) an isolated database + login role for an agent.

    Idempotent: re-running reuses the database and role, rotates the password.
    `admin_db_url` must be a connection for a role with CREATEDB + CREATEROLE
    (the control-plane tenant master).
    """
    db_name = _safe_db_name(agent_slug)
    role = db_name
    password = _gen_password()
    admin_role = _admin_role(admin_db_url)

    # Step 1: role + database live in the cluster, created from any DB
    # connection. CREATE DATABASE cannot run in a transaction → AUTOCOMMIT.
    engine = create_async_engine(admin_db_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            role_exists = await conn.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            )
            if role_exists:
                # Only rotate the password — restating NOSUPERUSER etc. would
                # require the SUPERUSER attribute, which the master lacks.
                await conn.execute(text(
                    f'ALTER ROLE "{role}" WITH LOGIN PASSWORD \'{password}\''
                ))
            else:
                await conn.execute(text(
                    f'CREATE ROLE "{role}" WITH LOGIN PASSWORD \'{password}\' '
                    f'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT '
                    f'CONNECTION LIMIT {ROLE_CONNECTION_LIMIT}'
                ))

            # Plan 071: the shared cluster has ~100 usable slots. Cap each
            # role just above the fleet pool bounds (pool 2 + overflow 3) and
            # have the server evict idle sessions — the client's
            # pool_recycle=300 would discard any conn idle >5min at next
            # checkout anyway, so a 15min server-side kill is invisible.
            # Plan 073: a machine restart/update leaves the old process's
            # pool as orphaned server backends (no FIN from a halted VM) —
            # with limit 6 the new process hit TooManyConnectionsError until
            # they aged out. Limit covers old+new pool (2×5) and per-role TCP
            # keepalives reap dead peers in ~60 s (server default is 10 min).
            for stmt in role_settings_sql(role):
                await conn.execute(text(stmt))

            # Postgres 16 requires the creating role to be a member of the
            # owner role before CREATE DATABASE ... OWNER. The membership also
            # lets the admin act as the DB owner for extension install.
            await conn.execute(text(f'GRANT "{role}" TO "{admin_role}"'))

            db_exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": db_name}
            )
            if not db_exists:
                await conn.execute(text(f'CREATE DATABASE "{db_name}" OWNER "{role}"'))
                log.info("Created tenant database %s (owner %s)", db_name, role)

            # Lock down: only the tenant role + the admin may connect.
            await conn.execute(text(f'REVOKE CONNECT ON DATABASE "{db_name}" FROM PUBLIC'))
            await conn.execute(text(f'GRANT CONNECT ON DATABASE "{db_name}" TO "{role}"'))
            await conn.execute(text(f'GRANT CONNECT ON DATABASE "{db_name}" TO "{admin_role}"'))
    finally:
        await engine.dispose()

    # Step 2: connect *into* the new DB as admin to install extensions and make
    # sure the tenant role owns its public schema (so Luna's create_all works).
    new_db_url = _swap_database(admin_db_url, db_name)
    engine2 = create_async_engine(new_db_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine2.connect() as conn:
            await conn.execute(text(f'ALTER SCHEMA public OWNER TO "{role}"'))
            await conn.execute(text(f'GRANT ALL ON SCHEMA public TO "{role}"'))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
    finally:
        await engine2.dispose()

    log.info("Provisioned isolated DB for %s → %s", agent_slug, db_name)
    return TenantDb(db_name=db_name, role=role, password=password)


async def provision_tenant_schema(db_url: str, schema_name: str) -> None:
    """LEGACY (pre-014): create a schema in a shared DB. Kept for old tests."""
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
