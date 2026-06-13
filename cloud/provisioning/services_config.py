"""Per-service config resolution for plan 016.

Two levels:
- `LunaImage.image_config["services"]` — the per-image default
- `Agent.config_overrides["services"]` — the per-agent override

The agent override wins; the image default is next; a builtin fallback
exists for the rare case where neither carries a value.

Today only `composio.accounts_mode` is wired through — but the resolver
treats `services.{slug}.{field}` generically so adding the next service is a
one-liner.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import GatewayKey, GatewayService

ComposioAccountsMode = Literal["hosted", "user", "both"]
_VALID_MODES: tuple[ComposioAccountsMode, ...] = ("hosted", "user", "both")


def _get_service_field(config: dict | None, service: str, field: str):
    """Pull config["services"][service][field] safely; None if missing."""
    if not isinstance(config, dict):
        return None
    services = config.get("services")
    if not isinstance(services, dict):
        return None
    svc = services.get(service)
    if not isinstance(svc, dict):
        return None
    return svc.get(field)


def resolve_composio_accounts_mode(
    image_config: dict | None,
    agent_overrides: dict | None,
    *,
    hosted_key_provisioned: bool,
) -> ComposioAccountsMode:
    """Resolve the effective accounts mode for a machine.

    Order: agent override → image default → builtin (both/user depending on
    whether the hosted Composio key is even available).
    """
    for src in (agent_overrides, image_config):
        v = _get_service_field(src, "composio", "accounts_mode")
        if v in _VALID_MODES:
            return v  # type: ignore[return-value]
    return "both" if hosted_key_provisioned else "user"


def _get_role_model(config: dict | None, role: str) -> dict | None:
    """Pull config["models"][role] safely; None if missing or malformed."""
    if not isinstance(config, dict):
        return None
    models = config.get("models")
    if not isinstance(models, dict):
        return None
    entry = models.get(role)
    if not isinstance(entry, dict):
        return None
    if not entry.get("model"):
        return None
    return {
        "provider": entry.get("provider") or "anthropic",
        "model": entry["model"],
    }


def resolve_models(
    image_config: dict | None,
    agent_overrides: dict | None,
) -> dict:
    """Resolve effective {primary, fast} model selection for a machine.

    Per role: agent override → image default → builtin fallback (anthropic
    sonnet 4 for both, matching DEFAULT_IMAGE_CONFIG).
    """
    fallback = {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}
    out: dict[str, dict] = {}
    for role in ("primary", "fast"):
        out[role] = (
            _get_role_model(agent_overrides, role)
            or _get_role_model(image_config, role)
            or fallback
        )
    return out


async def hosted_composio_key_provisioned(db: AsyncSession) -> bool:
    """True iff the composio service is enabled, provisioned by default,
    AND has at least one active key in its pool."""
    svc = (await db.execute(
        select(GatewayService).where(GatewayService.slug == "composio")
    )).scalar_one_or_none()
    if not svc or not svc.enabled or not svc.provision_by_default:
        return False
    count = (await db.execute(
        select(func.count()).select_from(GatewayKey).where(
            GatewayKey.service_slug == "composio",
            GatewayKey.is_active.is_(True),
        )
    )).scalar()
    return bool(count and count > 0)
