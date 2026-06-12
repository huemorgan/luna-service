"""Provisioning workflow — creates schema, derives vault key, spawns Luna."""

from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from cloud.db.models import Account, Agent, LunaImage
from cloud.db.session import get_session as get_db_session
from cloud.db.tenant_provisioner import _safe_schema, provision_tenant_schema
from cloud.gateway.provision_env import build_gateway_env
from cloud.runtime.base import AgentSpec
from cloud.runtime.docker_local import DockerLocalRuntime
from cloud.runtime.fly_machines import FlyMachinesRuntime
from cloud.vault.keygen import derive_tenant_vault_key

log = logging.getLogger(__name__)


def _get_runtime():
    kind = os.environ.get("CLOUD_RUNTIME", "docker-local")
    if kind == "docker-local":
        return DockerLocalRuntime()
    if kind in ("fly-machines", "fly"):
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
        if "+asyncpg" not in luna_db_url:
            luna_db_url = luna_db_url.replace("postgresql://", "postgresql+asyncpg://")
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
                    slug=f"{account.slug}-my-luna",
                    status="provisioning",
                )
                db.add(agent)
                await db.flush()

        schema_name = _safe_schema(agent.slug)
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

    # Gateway env: proxy base URLs + tenant token — no real provider keys.
    async with get_db_session() as db:
        llm_keys = await build_gateway_env(db, agent.id)
        await db.commit()

    # Look up the main image to use for provisioning
    image_tag = "local-luna-luna:latest"
    image_version = None
    image_config: dict = {}
    async with get_db_session() as db:
        main_image = (await db.execute(
            select(LunaImage).where(LunaImage.is_main == True, LunaImage.build_status == "built")  # noqa: E712
        )).scalar_one_or_none()
        if main_image:
            image_tag = main_image.registry_tag
            image_version = main_image.version
            image_config = main_image.image_config or {}

    try:
        runtime = _get_runtime()
    except Exception as e:
        log.error("Runtime init failed for %s: %s", account.slug, e)
        async with get_db_session() as db:
            agent = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
            agent.status = "error"
            agent.error_message = f"Runtime configuration error: {e}"
            agent.error_at = datetime.now(timezone.utc)
            await db.commit()
        raise

    spec = AgentSpec(
        account_slug=account.slug,
        agent_slug=agent.slug,
        db_schema=schema_name,
        db_url=luna_db_url,
        vault_key=vault_key.hex(),
        trusted_proxy_secret=proxy_secret,
        llm_keys=llm_keys,
        image_tag=image_tag,
        image_config=image_config,
    )

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
        agent.image_version = image_version
        agent.error_message = None
        agent.error_at = None
        await db.commit()
        await db.refresh(agent)

    log.info("Provisioned Luna for %s → %s", account.slug, handle.internal_url)
    return agent


async def provision_luna_for_account_with_image(
    account_id: str, *, agent_id: str, image_id: str,
) -> Agent:
    """Like provision_luna_for_account but uses a specific image instead of main."""
    async with get_db_session() as db:
        image = (await db.execute(
            select(LunaImage).where(LunaImage.id == image_id)
        )).scalar_one_or_none()
        if not image or image.build_status != "built":
            log.error("Image %s not found or not built", image_id)
            async with get_db_session() as db2:
                agent = (await db2.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
                agent.status = "error"
                agent.error_message = "Selected image not found or not built"
                from datetime import datetime, timezone
                agent.error_at = datetime.now(timezone.utc)
                await db2.commit()
            return  # type: ignore[return-value]

        # Temporarily set this image as the one to use by patching the lookup
        # We reuse the main provisioning flow but override the image selection
        account = (await db.execute(
            select(Account).where(Account.id == account_id)
        )).scalar_one()

        agent = (await db.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if not agent:
            log.error("Agent %s not found", agent_id)
            return  # type: ignore[return-value]

        schema_name = _safe_schema(agent.slug)
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
        from cloud.db.tenant_provisioner import provision_tenant_schema
        await provision_tenant_schema(tenant_db_url, schema_name)
    except Exception as e:
        log.error("Schema provisioning failed for %s: %s", agent.slug, e)
        async with get_db_session() as db:
            agent = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
            agent.status = "error"
            agent.error_message = f"Database setup failed: {e}"
            agent.error_at = datetime.now(timezone.utc)
            await db.commit()
        raise

    root_key = bytes.fromhex(os.environ.get("CLOUD_VAULT_ROOT_KEY", "a" * 64))
    vault_key = derive_tenant_vault_key(root_key, str(account.id))
    proxy_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", secrets.token_urlsafe(32))
    luna_db_url = _build_luna_db_url(tenant_db_url)

    # Gateway env: proxy base URLs + tenant token — no real provider keys.
    async with get_db_session() as db:
        llm_keys = await build_gateway_env(db, agent.id)
        await db.commit()

    image_config = image.image_config or {}

    try:
        runtime = _get_runtime()
    except Exception as e:
        log.error("Runtime init failed for %s: %s", agent.slug, e)
        async with get_db_session() as db:
            agent = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
            agent.status = "error"
            agent.error_message = f"Runtime configuration error: {e}"
            agent.error_at = datetime.now(timezone.utc)
            await db.commit()
        raise

    spec = AgentSpec(
        account_slug=account.slug,
        agent_slug=agent.slug,
        db_schema=schema_name,
        db_url=luna_db_url,
        vault_key=vault_key.hex(),
        trusted_proxy_secret=proxy_secret,
        llm_keys=llm_keys,
        image_tag=image.registry_tag,
        image_config=image_config,
    )

    try:
        handle = await runtime.provision(spec)
    except Exception as e:
        log.error("Provisioning failed for %s: %s", agent.slug, e)
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
        agent.image_version = image.version
        agent.error_message = None
        agent.error_at = None
        await db.commit()
        await db.refresh(agent)

    log.info("Provisioned test Luna for %s on image %s → %s", account.slug, image.version, handle.internal_url)
    return agent
