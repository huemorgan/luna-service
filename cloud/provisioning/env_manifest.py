"""Env-var manifest for tenant machines (plan 029).

Single source of truth for *describing* (not building) the env a machine runs
with — used by the admin UI to:
  * show the env template every NEW machine receives (Defaults → Env vars), and
  * show + audit a LIVE machine's actual env (Machines → Env vars).

Mirrors the assembly in ``runtime/fly_machines.py::provision`` +
``gateway/provision_env.py::build_gateway_env`` but is read-only and
secrets-free: dynamic per-agent values are rendered as ``{{placeholder}}``
strings and concrete secrets are masked. It NEVER issues a token or decrypts a
key.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.config import get_settings
from cloud.db.models import GatewayService
from cloud.gateway.provision_env import HOST_NAME, LEGACY_REAL_KEY_VARS
from cloud.provisioning.services_config import (
    hosted_composio_key_provisioned,
    resolve_composio_accounts_mode,
)
from cloud.runtime.fly_machines import files_env

# Vars whose value is per-agent / derived at provision time. In the defaults
# template these show a placeholder instead of a fixed value.
DYNAMIC_VARS: frozenset[str] = frozenset({
    "LUNA_TRUSTED_PROXY_SECRET",
    "LUNA_DATABASE_URL",
    "LUNA_VAULT_MASTER_KEY",
    "LUNA_GATEWAY_TOKEN",
    "LUNA_COMPOSIO_WEBHOOK_SECRET",
    "LUNA_MODEL_CATALOG",
})

# Explicit non-secret allowlist for names that would otherwise trip the
# substring heuristic below (e.g. a *_BASE_URL is not a secret).
_NOT_SECRET: frozenset[str] = frozenset({
    "LUNA_MODEL_CATALOG",
})

_SECRET_SUBSTRINGS = ("SECRET", "TOKEN", "PASSWORD", "_API_KEY", "MASTER_KEY")


def is_secret(name: str) -> bool:
    """True for values we must never echo back in clear text."""
    if name in _NOT_SECRET:
        return False
    if name == "LUNA_DATABASE_URL":  # carries the role password
        return True
    upper = name.upper()
    return any(s in upper for s in _SECRET_SUBSTRINGS)


def is_dynamic(name: str) -> bool:
    """True when the value is injected per-agent / derived at provision time."""
    if name in DYNAMIC_VARS:
        return True
    # Proxy device-token aliases: <SVC>_API_KEY and the LUNA_ variants carry the
    # per-agent token, so they're dynamic too.
    return name.endswith("_API_KEY")


def mask(value: str | None) -> str:
    """Mask a secret value — length only, never the content."""
    if not value:
        return "•••• (empty)"
    return f"•••• ({len(value)} chars)"


def _entry(name: str, *, value: str | None = None, placeholder: str | None = None,
           source: str) -> dict:
    return {
        "name": name,
        "value": value,
        "placeholder": placeholder,
        "source": source,
        "secret": is_secret(name),
        "dynamic": is_dynamic(name),
    }


# Human placeholders for the dynamic per-agent vars (shown in the template view).
_PLACEHOLDERS: dict[str, str] = {
    "LUNA_TRUSTED_PROXY_SECRET": "{{per-agent proxy secret (derived)}}",
    "LUNA_DATABASE_URL": "{{per-agent isolated Postgres URL}}",
    "LUNA_VAULT_MASTER_KEY": "{{per-tenant vault key (derived)}}",
    "LUNA_GATEWAY_TOKEN": "{{per-agent device token (lsv1-…)}}",
    "LUNA_COMPOSIO_WEBHOOK_SECRET": "{{per-agent relay secret (derived)}}",
    "LUNA_MODEL_CATALOG": "{{system model catalog (JSON)}}",
}


async def default_env_manifest(db: AsyncSession, image_config: dict) -> list[dict]:
    """The env template every new machine receives — dynamic values as placeholders."""
    settings = get_settings()
    base = settings.base_url.rstrip("/")
    entries: list[dict] = []

    # 1. Static platform vars (runtime/fly_machines.py).
    entries += [
        _entry("LUNA_ENV", value="production", source="platform"),
        _entry("LUNA_AUTH_MODE", value="trusted_proxy", source="platform"),
        _entry("LUNA_TRUSTED_PROXY_SECRET",
               placeholder=_PLACEHOLDERS["LUNA_TRUSTED_PROXY_SECRET"], source="platform"),
        _entry("LUNA_DATABASE_URL",
               placeholder=_PLACEHOLDERS["LUNA_DATABASE_URL"], source="platform"),
        _entry("LUNA_VAULT_MASTER_KEY",
               placeholder=_PLACEHOLDERS["LUNA_VAULT_MASTER_KEY"], source="platform"),
        _entry("LUNA_REDIS_URL", value="", source="platform"),
        _entry("LUNA_CORS_ORIGINS", value="*", source="platform"),
        _entry("LUNA_LOG_LEVEL", value="INFO", source="platform"),
    ]

    # 2. Gateway block (gateway/provision_env.py) — proxy base-urls + token.
    entries.append(_entry("LUNA_HOST_NAME", value=HOST_NAME, source="gateway"))
    services = (await db.execute(
        select(GatewayService).where(
            GatewayService.enabled.is_(True),
            GatewayService.provision_by_default.is_(True),
        )
    )).scalars().all()
    for svc in services:
        base_url = f"{base}/proxy/{svc.slug}"
        entries.append(_entry(svc.luna_env_base_url_var, value=base_url, source="gateway"))
        entries.append(_entry(svc.luna_env_key_var,
                              placeholder="{{per-agent device token}}", source="gateway"))
        # SDK-standard aliases (ANTHROPIC_BASE_URL, …) the runtime also emits.
        for luna_var in (svc.luna_env_base_url_var, svc.luna_env_key_var):
            if luna_var.startswith("LUNA_"):
                alias = luna_var.removeprefix("LUNA_")
                if is_secret(alias):
                    entries.append(_entry(alias, placeholder="{{per-agent device token}}", source="gateway"))
                else:
                    entries.append(_entry(alias, value=base_url, source="gateway"))

    entries.append(_entry("LUNA_GATEWAY_URL", value=f"{base}/proxy", source="gateway"))
    entries.append(_entry("LUNA_GATEWAY_TOKEN",
                          placeholder=_PLACEHOLDERS["LUNA_GATEWAY_TOKEN"], source="gateway"))

    accounts_mode = resolve_composio_accounts_mode(
        image_config, None, hosted_key_provisioned=await hosted_composio_key_provisioned(db),
    )
    entries.append(_entry("LUNA_CONNECTORS_ACCOUNTS_MODE", value=accounts_mode, source="gateway"))
    entries.append(_entry("LUNA_COMPOSIO_WEBHOOK_SECRET",
                          placeholder=_PLACEHOLDERS["LUNA_COMPOSIO_WEBHOOK_SECRET"], source="gateway"))

    import os
    for var in LEGACY_REAL_KEY_VARS:
        if os.environ.get(var):
            entries.append(_entry(var, placeholder="{{real provider key (legacy, server-side)}}", source="gateway"))

    # 3. Models (runtime/fly_machines.py + plan 018 catalog).
    models_cfg = image_config.get("models", {}) if isinstance(image_config, dict) else {}
    primary = (models_cfg.get("primary") or {})
    fast = (models_cfg.get("fast") or {})
    if primary.get("model"):
        entries.append(_entry("LUNA_PRIMARY_MODEL",
                              value=f"{primary.get('provider', 'anthropic')}:{primary['model']}", source="models"))
    if fast.get("model"):
        entries.append(_entry("LUNA_FAST_MODEL",
                              value=f"{fast.get('provider', 'anthropic')}:{fast['model']}", source="models"))
    entries.append(_entry("LUNA_MODEL_CATALOG",
                          placeholder=_PLACEHOLDERS["LUNA_MODEL_CATALOG"], source="models"))

    # 4. Disabled plugins (from image_config.plugins).
    plugins_cfg = image_config.get("plugins", {}) if isinstance(image_config, dict) else {}
    disabled = [k for k, v in plugins_cfg.items() if v is False]
    if disabled:
        entries.append(_entry("LUNA_DISABLED_PLUGINS", value=",".join(disabled), source="plugins"))

    # 5. image_config.env overrides.
    env_overrides = image_config.get("env", {}) if isinstance(image_config, dict) else {}
    for k, v in env_overrides.items():
        entries.append(_entry(k, value=None if is_secret(k) else str(v),
                              placeholder=mask(str(v)) if is_secret(k) else None, source="image-config"))

    # 6. Files env (persistent volume wiring).
    for k, v in files_env().items():
        entries.append(_entry(k, value=v, source="files"))

    return entries


def live_machine_env(config_env: dict | None, expected_names: set[str]) -> dict:
    """Describe a live machine's actual Fly env: classify + mask, flag missing.

    ``config_env`` is the ``config.env`` dict straight off the Fly machine record.
    ``expected_names`` are names the template says the machine should have — any
    that are absent are returned in ``missing`` (e.g. a stale machine lacking the
    gateway pair)."""
    config_env = config_env or {}
    entries: list[dict] = []
    for name in sorted(config_env.keys()):
        raw = config_env[name]
        secret = is_secret(name)
        entries.append({
            "name": name,
            "value": mask(raw) if secret else raw,
            "placeholder": None,
            "source": "live",
            "secret": secret,
            "dynamic": is_dynamic(name),
        })
    missing = sorted(n for n in expected_names if n not in config_env)
    return {"entries": entries, "missing": missing}
