"""Apply a gateway env change to a running machine (plan 026 §Applying to running machines).

When a binding or opt-in install changes what services an agent should reach, we
recompute its gateway env and push the delta with ``update_machine_env`` (Fly
recreates the machine in place — id + volume preserved — and restarts it with the
new env/token). Best-effort installs the plugin code first so it's present when
the machine comes back. Never raises; returns a result summary.
"""

from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy import select

from cloud.db.models import Agent, LunaImage
from cloud.db.session import get_session as get_db_session
from cloud.gateway.provision_env import build_gateway_env

log = logging.getLogger(__name__)


async def _agent_image_config(db, agent: Agent) -> dict:
    """The agent's effective image_config (baked plugin_set lives here)."""
    from cloud.api.admin_routes import _default_image_config
    from cloud.provisioning.image_defaults import effective_env_overrides

    default_cfg = await _default_image_config(db)
    img = None
    if agent.image_version:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.version == agent.image_version)
        )).scalar_one_or_none()
    img_cfg = (img.image_config if img else None) or {}
    cfg = {**default_cfg, **img_cfg}
    # Plan 072: `env` is a one-level dict — the image's own entries overlay the
    # admin-stored defaults instead of replacing the whole block, matching how
    # provisioning composes it (`effective_env_overrides`).
    cfg["env"] = effective_env_overrides(default_cfg, img_cfg)
    return cfg


async def apply_gateway_env_delta(
    agent_id: uuid.UUID,
    *,
    marketplace_url: str | None = None,
    plugin_name: str | None = None,
    admin_email: str | None = None,
) -> dict:
    """Best-effort: install the plugin code, recompute gateway env, push to machine."""
    result = {"plugin_installed": False, "env_pushed": False, "note": None}

    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if not agent:
            result["note"] = "agent_not_found"
            return result
        image_config = await _agent_image_config(db, agent)
        # revoke_existing=False: the machine's live token must stay valid until
        # the new env is confirmed pushed — a failed push below is best-effort
        # and must not leave the machine holding a revoked token.
        env = await build_gateway_env(
            db, agent.id, image_config=image_config,
            agent_overrides=agent.config_overrides, revoke_existing=False,
        )
        await db.commit()
        runtime_ref = agent.runtime_ref
        agent_snapshot = agent
    new_token = env.get("LUNA_GATEWAY_TOKEN")

    async def _finalize_tokens(pushed: bool) -> None:
        from cloud.gateway.tokens import revoke_other_tokens, revoke_raw_token
        if not new_token:
            return
        try:
            async with get_db_session() as db:
                if pushed:
                    await revoke_other_tokens(db, agent_id, new_token)
                else:
                    await revoke_raw_token(db, new_token)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — never crash the admin action
            log.error("token finalize (pushed=%s) failed for agent %s: %s",
                      pushed, agent_id, exc)

    # 1. Install the plugin code on the machine (best-effort; needs marketplace_url).
    if marketplace_url and plugin_name and admin_email:
        from cloud.api.agent_routes import _tenant_request
        code, _ = await _tenant_request(
            agent_snapshot, "POST", "/api/p/plugin-marketplace/install",
            {"marketplace_url": marketplace_url, "name": plugin_name},
            user_email=admin_email,
            auth="jwt",  # install is a WRITE — agent core 401s proxy-secret-only auth
        )
        result["plugin_installed"] = code == 200

    # 2. Push the gateway env delta (restarts the machine with the new token/vars).
    if not runtime_ref:
        result["note"] = "no_runtime"
        await _finalize_tokens(pushed=False)
        return result
    if not os.environ.get("FLY_API_TOKEN"):
        result["note"] = "fly_not_configured"
        await _finalize_tokens(pushed=False)
        return result
    try:
        from cloud.runtime.fly_machines import FlyMachinesRuntime
        fly = FlyMachinesRuntime()
        await fly.update_machine_env(runtime_ref, env)
        result["env_pushed"] = True
    except Exception as exc:  # noqa: BLE001 — never crash the admin action
        log.error("gateway env delta push failed for agent %s: %s", agent_id, exc)
        result["note"] = f"env_push_failed: {type(exc).__name__}"
        from cloud.observability.error_sink import record_error_event
        await record_error_event(
            kind="gateway_auth", severity="error",
            message=f"Gateway env push failed for agent (env_push_failed: {type(exc).__name__}) "
                    "— machine keeps its previous token",
            route="gateway_env_delta", agent_id=agent_id,
        )
    await _finalize_tokens(pushed=result["env_pushed"])
    return result
