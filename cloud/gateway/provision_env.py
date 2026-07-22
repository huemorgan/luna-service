"""Registry-driven env injection for tenant machines.

Replaces the hardcoded real-key loop in provisioning: machines get proxy
base URLs + one lsv1- tenant token, never a real provider key.
"""

from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.config import get_settings
from cloud.db.models import GatewayService
from cloud.gateway.catalog import bindings_for_plugins, effective_plugin_names
from cloud.gateway.crypto import decrypt_key
from cloud.gateway.keys import has_active_key, resolve_keys
from cloud.gateway.registry import get_service
from cloud.gateway.tokens import issue_token

log = logging.getLogger(__name__)

HOST_NAME = "Luna Cloud"


def _emit_proxy_service(env: dict[str, str], svc: GatewayService, base: str, token: str) -> None:
    """Proxy mode: base-url override + tenant token (real key stays server-side)."""
    env[svc.luna_env_base_url_var] = f"{base}/proxy/{svc.slug}"
    env[svc.luna_env_key_var] = token
    # SDK-standard aliases (ANTHROPIC_BASE_URL, …) for the pydantic-ai chat path.
    for luna_var in (svc.luna_env_base_url_var, svc.luna_env_key_var):
        if luna_var.startswith("LUNA_"):
            env[luna_var.removeprefix("LUNA_")] = env[luna_var]


def _emit_extra_env(env: dict[str, str], svc: GatewayService) -> None:
    """Inject a service's extra_env — plain env vars a bound plugin needs on the
    machine that aren't the proxy pair (e.g. OAuth app credentials like
    LUNA_MONDAY_CLIENT_ID/_SECRET). Values are AES-GCM encrypted at rest; decrypt
    on the way out. A bad value is logged and skipped, never sinks the machine."""
    for var, enc in (svc.extra_env or {}).items():
        try:
            env[var] = decrypt_key(enc)
        except Exception:  # noqa: BLE001 — one bad var must not block provisioning
            log.error("gateway extra_env decrypt failed for %s.%s", svc.slug, var)

# Services Luna can't route through the proxy yet (no base-url support on the
# Luna side until 007.001 lands). The real key keeps being injected for these.
LEGACY_REAL_KEY_VARS = ("LUNA_TAVILY_API_KEY", "LUNA_ELEVENLABS_API_KEY")


async def build_gateway_env(
    db: AsyncSession,
    agent_id: uuid.UUID,
    *,
    image_config: dict | None = None,
    agent_overrides: dict | None = None,
    revoke_existing: bool = True,
) -> dict[str, str]:
    """Env vars for a tenant machine: proxy URLs + tenant token + branding.

    ``revoke_existing=False`` keeps the machine's current token valid while the
    new env is pushed — callers must then finalize with
    ``tokens.revoke_other_tokens`` on success (or ``revoke_raw_token`` on
    failure). Fresh provisioning keeps the default.
    """
    settings = get_settings()
    base = settings.base_url.rstrip("/")

    token = await issue_token(db, agent_id, revoke_existing=revoke_existing)

    services = (await db.execute(
        select(GatewayService).where(
            GatewayService.enabled.is_(True),
            GatewayService.provision_by_default.is_(True),
        )
    )).scalars().all()

    env: dict[str, str] = {"LUNA_HOST_NAME": HOST_NAME}
    emitted: set[str] = set()
    for svc in services:
        _emit_proxy_service(env, svc, base, token)
        _emit_extra_env(env, svc)
        emitted.add(svc.slug)

    # Plan 026 — membership-driven services: any plugin this agent effectively
    # runs (baked plugin_set ∪ installed opt-in) whose catalog binding points at
    # a keyed service. provision_by_default services are already emitted above.
    plugin_names = effective_plugin_names(image_config, agent_overrides)
    bindings = await bindings_for_plugins(db, plugin_names)
    for binding in bindings:
        svc = await get_service(db, binding.service_slug)
        if svc is None or not svc.enabled or svc.slug in emitted:
            continue
        # OAuth app credentials (extra_env) are needed whenever the bound plugin
        # runs — inject them independent of the data-key gate below (a tenant may
        # run the OAuth handshake before any proxy key is provisioned).
        _emit_extra_env(env, svc)
        # Key-gated: never provision a keyless proxy / env binding.
        if not await has_active_key(db, svc.slug, agent_id):
            log.info("gateway binding %s → %s: no active key, extra_env only", binding.plugin_name, svc.slug)
            continue
        if binding.key_mode == "env":
            # Admin opt-in fallback: the real key lands on the machine (compromised)
            # for plugins that can't be proxied. No base-url override — direct upstream.
            pool = await resolve_keys(db, svc.slug, agent_id)
            if pool:
                env[svc.luna_env_key_var] = decrypt_key(pool[0].api_key_enc)
        else:  # proxy
            _emit_proxy_service(env, svc, base, token)
        emitted.add(svc.slug)

    # Plan 026.1 — single gateway pair (additive). The vault builds
    # {LUNA_GATEWAY_URL}/<slug> per connection and authenticates with this token.
    # Kept alongside the per-service vars above for back-compat until luna ships
    # ctx.vault.connect() (proposal 026.1-vault-virtual-keys).
    env["LUNA_GATEWAY_URL"] = f"{base}/proxy"
    env["LUNA_GATEWAY_TOKEN"] = token

    # Legacy exception — documented in plan 013 / tests 07.
    for var in LEGACY_REAL_KEY_VARS:
        val = os.environ.get(var, "")
        if val:
            env[var] = val

    log.info(
        "gateway env for agent %s: %s (+ %d legacy vars)",
        agent_id,
        [s.slug for s in services],
        sum(1 for v in LEGACY_REAL_KEY_VARS if os.environ.get(v)),
    )
    return env
