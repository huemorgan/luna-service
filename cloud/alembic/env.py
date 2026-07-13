"""Alembic env for the control-plane database."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import cloud.billing.models  # noqa: F401 — billing tables join Base.metadata
from cloud.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Runtime URL comes from the environment (deploy runs migrations before the
# app starts); the ini value is the local-dev fallback.
_env_url = os.environ.get("CLOUD_DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

target_metadata = Base.metadata

# CLOUD_ALEMBIC_SCOPE=core restricts autogenerate to the pre-billing schema.
# Used only when (re)generating the 0001 baseline; harmless otherwise.
CORE_TABLES = {
    "users", "accounts", "memberships", "agents", "luna_images",
    "gateway_services", "plugin_catalog", "gateway_models", "gateway_keys",
    "gateway_tenant_tokens", "usage_events", "composio_account_links",
    "relay_deliveries", "audit_log", "app_settings",
}


def include_object(obj, name, type_, reflected, compare_to):
    if os.environ.get("CLOUD_ALEMBIC_SCOPE") == "core":
        if type_ == "table":
            return name in CORE_TABLES
        table = getattr(obj, "table", None)
        if table is not None:
            return table.name in CORE_TABLES
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection, target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
