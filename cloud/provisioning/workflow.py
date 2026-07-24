"""Provisioning workflow — creates an isolated DB, derives secrets, spawns Luna.

Plan 014: each agent gets its own Postgres database + login role (hard
isolation) and an agent-specific trusted-proxy secret. No shared DB creds or
shared proxy secret ever reach a tenant machine.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from cloud.db.models import Account, Agent, LunaImage
from cloud.db.session import get_session as get_db_session
from cloud.db.tenant_provisioner import (
    TenantDb,
    _safe_db_name,
    _swap_database,
    provision_tenant_database,
)
from cloud.gateway.provision_env import build_gateway_env
from cloud.provisioning.image_defaults import resolved_default_config
from cloud.provisioning.model_catalog import resolve_default_heads, system_catalog
from cloud.relay.secrets import derive_relay_secret
from cloud.runtime.base import AgentSpec
from cloud.runtime.docker_local import DockerLocalRuntime
from cloud.runtime.fly_machines import FlyMachinesRuntime
from cloud.runtime.proxy_secret import derive_jwt_secret, derive_proxy_secret
from cloud.vault.keygen import derive_tenant_vault_key

log = logging.getLogger(__name__)


def _get_runtime():
    kind = os.environ.get("CLOUD_RUNTIME", "docker-local")
    if kind == "docker-local":
        return DockerLocalRuntime()
    if kind in ("fly-machines", "fly"):
        return FlyMachinesRuntime()
    raise ValueError(f"Unknown runtime: {kind}")


def _admin_tenant_url() -> str:
    return os.environ.get(
        "CLOUD_TENANT_DATABASE_URL",
        os.environ.get("CLOUD_DATABASE_URL", "postgresql+asyncpg://luna:luna@localhost:5435/lunaservice"),
    )


def _host_for_runtime(url: str) -> str:
    """Convert a control-plane DB URL into one a tenant machine can reach."""
    runtime_kind = os.environ.get("CLOUD_RUNTIME", "docker-local")

    if runtime_kind == "docker-local" and "localhost" in url:
        url = url.replace("localhost:5435", "luna-service-postgres:5432")
        url = url.replace("localhost:5432", "luna-service-postgres:5432")

    if runtime_kind == "fly-machines":
        if "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://")
        url = re.sub(
            r"@(dpg-[a-z0-9]+(?:-a)?)/",
            r"@\1.oregon-postgres.render.com/",
            url,
        )
    elif runtime_kind == "docker-local":
        # Luna only speaks asyncpg — keep the driver even after the host swap
        # above removed "localhost" from the URL.
        if "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://")
    elif "localhost" not in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://")

    return url


def _compose_agent_db_url(admin_url: str, tenant_db: TenantDb) -> str:
    """Build the agent's own connection string from the admin URL + creds."""
    url = re.sub(r"://[^@]+@", f"://{tenant_db.role}:{tenant_db.password}@", admin_url, count=1)
    url = _swap_database(url, tenant_db.db_name)
    return _host_for_runtime(url)


async def _set_agent_error(agent_id, message: str) -> None:
    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
        agent.status = "error"
        agent.error_message = message
        agent.error_at = datetime.now(timezone.utc)
        await db.commit()


async def _provision_core(
    account: Account,
    agent: Agent,
    *,
    image_tag: str,
    image_version: str | None,
    image_config: dict,
) -> Agent:
    """Shared provisioning: isolated DB, secrets, spec, runtime, record update."""
    agent_id = agent.id
    agent_slug = agent.slug

    # 1. Isolated per-agent database + login role.
    admin_url = _admin_tenant_url()
    try:
        tenant_db = await provision_tenant_database(admin_url, agent_slug)
    except Exception as e:
        log.error("DB provisioning failed for %s: %s", agent_slug, e)
        await _set_agent_error(agent_id, f"Database setup failed: {e}")
        raise

    luna_db_url = _compose_agent_db_url(admin_url, tenant_db)

    # 2. Per-tenant vault key + per-agent trusted-proxy secret.
    root_key = bytes.fromhex(os.environ.get("CLOUD_VAULT_ROOT_KEY", "a" * 64))
    vault_key = derive_tenant_vault_key(root_key, str(account.id))

    root_proxy_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", secrets.token_urlsafe(32))
    proxy_secret = derive_proxy_secret(root_proxy_secret, str(agent_id))
    # Plan 042: stable per-agent JWT secret so machine restarts don't
    # invalidate every outstanding token (Fly HOME is ephemeral).
    jwt_secret = derive_jwt_secret(root_proxy_secret, str(agent_id))

    # 3. Gateway env: proxy base URLs + tenant token — no real provider keys.
    #    Plan 016: pass image_config + agent overrides for per-service env vars.
    #    Plan 018: also resolve the system model catalog + default heads here.
    #    060/fix3: revoke_existing=False — on a RECREATE the old machine's live
    #    token must stay valid until the new machine is actually up (revoking
    #    up-front 401'd every in-flight gateway call while the new machine
    #    booted, and left the agent tokenless when provisioning failed). Old
    #    tokens are revoked below, only after the runtime reports success.
    async with get_db_session() as db:
        llm_keys = await build_gateway_env(
            db, agent_id,
            image_config=image_config,
            agent_overrides=agent.config_overrides,
            revoke_existing=False,
        )
        catalog = await system_catalog(db)
        # Plan 036: the admin-set default machine params apply when the image
        # didn't set its own; the image's machine block still wins per-field.
        stored_defaults = await resolved_default_config(db)
        default_machine = stored_defaults.get("machine", {})
        await db.commit()
    heads = resolve_default_heads(
        catalog, image_config, agent.config_overrides, image_defaults=stored_defaults,
    )

    # Plan 015: per-agent Composio relay secret — the trigger relay signs
    # forwarded webhook events with this; Luna verifies once 007.003 ships.
    llm_keys["LUNA_COMPOSIO_WEBHOOK_SECRET"] = derive_relay_secret(
        root_proxy_secret, str(agent_id)
    )

    try:
        runtime = _get_runtime()
    except Exception as e:
        log.error("Runtime init failed for %s: %s", agent_slug, e)
        await _set_agent_error(agent_id, f"Runtime configuration error: {e}")
        raise

    # Plan 018: merge resolved heads + system catalog into the effective config
    # the runtime injects (LUNA_PRIMARY_MODEL / LUNA_FAST_MODEL / LUNA_MODEL_CATALOG).
    effective_image_config = {**image_config}
    effective_image_config["machine"] = {**default_machine, **(image_config.get("machine") or {})}
    effective_image_config["models"] = {
        "primary": heads["primary"],
        "fast": heads["fast"],
        "catalog": catalog,
    }

    spec = AgentSpec(
        account_slug=account.slug,
        agent_slug=agent_slug,
        db_schema="",  # isolation is per-database now; schema is unused
        db_url=luna_db_url,
        vault_key=vault_key.hex(),
        trusted_proxy_secret=proxy_secret,
        jwt_secret=jwt_secret,
        llm_keys=llm_keys,
        image_tag=image_tag,
        image_config=effective_image_config,
    )

    new_token = llm_keys.get("LUNA_GATEWAY_TOKEN", "")

    try:
        handle = await runtime.provision(spec)
    except Exception as e:
        log.error("Provisioning failed for %s: %s", agent_slug, e)
        # 060/fix3: the new machine never came up — drop the token we minted
        # for it and leave the previous token (if any) untouched, so a running
        # old machine keeps working.
        try:
            from cloud.gateway.tokens import revoke_raw_token
            async with get_db_session() as db:
                await revoke_raw_token(db, new_token)
                await db.commit()
        except Exception:  # noqa: BLE001 — cleanup must not mask the provision error
            log.exception("token cleanup after failed provision for %s", agent_slug)
        await _set_agent_error(agent_id, f"Agent startup failed: {e}")
        raise

    # 060/fix3: the new machine is up with the new token in its env — NOW it's
    # safe to invalidate whatever the old machine was holding.
    try:
        from cloud.gateway.tokens import revoke_other_tokens
        async with get_db_session() as db:
            revoked = await revoke_other_tokens(db, agent_id, new_token)
            await db.commit()
        if revoked:
            log.info("revoked %d stale gateway token(s) for %s", revoked, agent_slug)
    except Exception:  # noqa: BLE001 — a failed revoke must not fail the provision
        log.exception("post-provision token revoke failed for %s", agent_slug)

    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
        agent.status = "running"
        agent.runtime_kind = handle.runtime_kind
        agent.runtime_ref = handle.runtime_ref
        agent.internal_url = handle.internal_url
        agent.db_schema = tenant_db.db_name  # store the agent's DB name
        # Plan 025.5: persist the per-agent Fly volume so recreate re-attaches it
        # and delete can clean it up. Only overwrite when the runtime reported one.
        if handle.extra.get("volume_id"):
            agent.volume_id = handle.extra["volume_id"]
            agent.volume_region = handle.extra.get("volume_region")
            agent.volume_size_gb = handle.extra.get("volume_size_gb")
        if image_version is not None:
            agent.image_version = image_version
        agent.error_message = None
        agent.error_at = None
        await db.commit()
        await db.refresh(agent)

    log.info("Provisioned Luna for %s → %s (db %s)", agent_slug, handle.internal_url, tenant_db.db_name)
    return agent


async def provision_luna_for_account(account_id: str, *, agent_id: str | None = None) -> Agent:
    """Provision a Luna instance for an account. Idempotent."""
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

        agent.status = "provisioning"
        agent.error_message = None
        agent.error_at = None
        await db.commit()
        await db.refresh(agent)
        account_obj = account

    # Look up the main image.
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

    return await _provision_core(
        account_obj, agent,
        image_tag=image_tag, image_version=image_version, image_config=image_config,
    )


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
            await _set_agent_error(agent_id, "Selected image not found or not built")
            return  # type: ignore[return-value]

        account = (await db.execute(
            select(Account).where(Account.id == account_id)
        )).scalar_one()

        agent = (await db.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if not agent:
            log.error("Agent %s not found", agent_id)
            return  # type: ignore[return-value]

        agent.status = "provisioning"
        agent.error_message = None
        agent.error_at = None
        await db.commit()
        await db.refresh(agent)
        account_obj = account
        image_tag = image.registry_tag
        image_version = image.version
        image_config = image.image_config or {}

    return await _provision_core(
        account_obj, agent,
        image_tag=image_tag, image_version=image_version, image_config=image_config,
    )
