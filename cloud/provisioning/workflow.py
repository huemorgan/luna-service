"""Provisioning workflow — creates schema, derives vault key, spawns Luna."""

from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from cloud.db.models import Account, Agent
from cloud.db.session import get_session as get_db_session
from cloud.db.tenant_provisioner import _safe_schema, provision_tenant_schema
from cloud.runtime.base import AgentSpec
from cloud.runtime.docker_local import DockerLocalRuntime
from cloud.runtime.fly_machines import FlyMachinesRuntime
from cloud.vault.keygen import derive_tenant_vault_key

log = logging.getLogger(__name__)


def _get_runtime():
    kind = os.environ.get("CLOUD_RUNTIME", "docker-local")
    if kind == "docker-local":
        return DockerLocalRuntime()
    if kind == "fly-machines":
        return FlyMachinesRuntime()
    raise ValueError(f"Unknown runtime: {kind}")


def _build_luna_db_url(tenant_db_url: str) -> str:
    """Convert the control-plane tenant DB URL into one the Luna container can reach."""
    runtime_kind = os.environ.get("CLOUD_RUNTIME", "docker-local")
    luna_db_url = tenant_db_url

    if runtime_kind == "docker-local" and "localhost" in luna_db_url:
        luna_db_url = luna_db_url.replace("localhost:5435", "luna-service-postgres:5432")
        luna_db_url = luna_db_url.replace("localhost:5432", "luna-service-postgres:5432")

    if runtime_kind == "fly-machines":
        luna_db_url = luna_db_url.replace("postgresql+asyncpg://", "postgresql://")
        luna_db_url = re.sub(
            r"@(dpg-[a-z0-9]+(?:-a)?)/",
            r"@\1.oregon-postgres.render.com/",
            luna_db_url,
        )
    elif "localhost" not in luna_db_url:
        luna_db_url = luna_db_url.replace("postgresql+asyncpg://", "postgresql://")

    return luna_db_url


async def provision_luna_for_account(account_id: str, *, agent_id: str | None = None) -> Agent:
    """Provision a Luna instance for an account. Idempotent.

    If agent_id is provided, provisions that specific agent.
    Otherwise creates a new agent record.
    """
    async with get_db_session() as db:
        account = (await db.execute(
            select(Account).where(Account.id == account_id)
        )).scalar_one()

        if agent_id:
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if not agent:
                log.error("Agent %s not found for provisioning", agent_id)
                return  # type: ignore[return-value]
            if agent.status == "running":
                log.info("Agent %s already running", agent_id)
                return agent
        else:
            agent = (await db.execute(
                select(Agent).where(Agent.account_id == account.id)
            )).scalar_one_or_none()

            if agent and agent.status == "running":
                log.info("Agent already running for %s", account.slug)
                return agent

            if not agent:
                agent = Agent(
                    account_id=account.id,
                    creator_id=account.created_by,
                    name="My Luna",
                    status="provisioning",
                )
                db.add(agent)
                await db.flush()

        schema_name = _safe_schema(account.slug)
        agent.db_schema = schema_name
        agent.status = "provisioning"
        agent.error_message = None
        agent.error_at = None
        await db.commit()

    tenant_db_url = os.environ.get(
        "CLOUD_TENANT_DATABASE_URL",
        os.environ.get("CLOUD_DATABASE_URL", "postgresql+asyncpg://luna:luna@localhost:5435/lunaservice"),
    )

    try:
        await provision_tenant_schema(tenant_db_url, schema_name)
    except Exception as e:
        log.error("Schema provisioning failed for %s: %s", account.slug, e)
        async with get_db_session() as db:
            agent = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
            agent.status = "error"
            agent.error_message = f"Database setup failed: {e}"
            agent.error_at = datetime.now(timezone.utc)
            await db.commit()
        raise

    root_key = bytes.fromhex(
        os.environ.get("CLOUD_VAULT_ROOT_KEY", "a" * 64)
    )
    vault_key = derive_tenant_vault_key(root_key, str(account.id))

    proxy_secret = os.environ.get(
        "CLOUD_TRUSTED_PROXY_SECRET",
        secrets.token_urlsafe(32),
    )

    luna_db_url = _build_luna_db_url(tenant_db_url)

    llm_keys = {}
    for key in ("LUNA_ANTHROPIC_API_KEY", "LUNA_OPENAI_API_KEY", "LUNA_TAVILY_API_KEY"):
        val = os.environ.get(key, "")
        if val:
            llm_keys[key] = val

    spec = AgentSpec(
        account_slug=account.slug,
        db_schema=schema_name,
        db_url=luna_db_url,
        vault_key=vault_key.hex(),
        trusted_proxy_secret=proxy_secret,
        llm_keys=llm_keys,
    )

    runtime = _get_runtime()
    try:
        handle = await runtime.provision(spec)
    except Exception as e:
        log.error("Provisioning failed for %s: %s", account.slug, e)
        async with get_db_session() as db:
            agent = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
            agent.status = "error"
            agent.error_message = f"Agent startup failed: {e}"
            agent.error_at = datetime.now(timezone.utc)
            await db.commit()
        raise

    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
        agent.status = "running"
        agent.runtime_kind = handle.runtime_kind
        agent.runtime_ref = handle.runtime_ref
        agent.internal_url = handle.internal_url
        agent.error_message = None
        agent.error_at = None
        await db.commit()
        await db.refresh(agent)

    log.info("Provisioned Luna for %s → %s", account.slug, handle.internal_url)
    return agent
