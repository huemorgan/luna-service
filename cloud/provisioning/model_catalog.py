"""Plan 018 — resolve the model catalog + default chain heads for a tenant.

The catalog is system-wide (gateway_models rows). The default head per purpose
comes from the agent override → image config → catalog recommended_default →
first in-catalog model of that kind. Heads are always validated to be in-catalog,
so we can never inject a model Luna would prune (007.016 self-heal).

Injected inward only (Luna never fetches): LUNA_MODEL_CATALOG (JSON of the
enabled rows) + LUNA_PRIMARY_MODEL / LUNA_FAST_MODEL (provider:model).
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import GatewayModel

log = logging.getLogger(__name__)

# Process-local TTL cache of the system catalog (it's system-wide, not per-agent),
# so the proxy hot path doesn't hit the DB on every request.
_CATALOG_TTL_SECONDS = 30.0
_catalog_cache: tuple[float, list[dict]] | None = None

# Purpose → which env head it drives.
PRIMARY_KIND = "reasoning"
FAST_KIND = "summarization"

# Last-resort builtin if the catalog is somehow empty (table not seeded yet).
_BUILTIN_PRIMARY = {"provider": "anthropic", "model": "claude-opus-4-6"}
_BUILTIN_FAST = {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}


def _entry_dict(m: GatewayModel) -> dict:
    """GatewayModel row → Luna ModelCatalogEntry shape (omit empty optionals)."""
    entry: dict = {"provider": m.provider, "model": m.model, "kinds": list(m.kinds or [])}
    if m.label:
        entry["label"] = m.label
    if m.context_window is not None:
        entry["context_window"] = m.context_window
    if m.aliases:
        entry["aliases"] = list(m.aliases)
    if m.tier:
        entry["tier"] = m.tier
    if m.input_cost is not None:
        entry["input_cost"] = m.input_cost
    if m.output_cost is not None:
        entry["output_cost"] = m.output_cost
    if m.recommended_default:
        entry["recommended_default"] = True
    if m.deprecated:
        entry["deprecated"] = True
    return entry


async def system_catalog(db: AsyncSession) -> list[dict]:
    """Enabled gateway_models rows in Luna's catalog-entry shape."""
    rows = (await db.execute(
        select(GatewayModel)
        .where(GatewayModel.enabled.is_(True))
        .order_by(GatewayModel.provider, GatewayModel.model)
    )).scalars().all()
    return [_entry_dict(m) for m in rows]


async def cached_system_catalog(db: AsyncSession) -> list[dict]:
    """system_catalog with a short process-local TTL — for the proxy hot path."""
    global _catalog_cache
    now = time.monotonic()
    if _catalog_cache is not None and now - _catalog_cache[0] < _CATALOG_TTL_SECONDS:
        return _catalog_cache[1]
    catalog = await system_catalog(db)
    _catalog_cache = (now, catalog)
    return catalog


def invalidate_catalog_cache() -> None:
    """Drop the cached catalog (call after any admin model write)."""
    global _catalog_cache
    _catalog_cache = None


def _models_for_kind(catalog: list[dict], kind: str) -> list[dict]:
    return [e for e in catalog if kind in (e.get("kinds") or [])]


def _in_catalog(catalog: list[dict], provider: str, model: str, kind: str) -> bool:
    for e in _models_for_kind(catalog, kind):
        if e["provider"] == provider and e["model"] == model:
            return True
        if model in (e.get("aliases") or []) and e["provider"] == provider:
            return True
    return False


def _catalog_default(catalog: list[dict], kind: str, fallback: dict) -> dict:
    """recommended_default of `kind`, else first model of `kind`, else fallback."""
    candidates = _models_for_kind(catalog, kind)
    for e in candidates:
        if e.get("recommended_default"):
            return {"provider": e["provider"], "model": e["model"]}
    if candidates:
        return {"provider": candidates[0]["provider"], "model": candidates[0]["model"]}
    return fallback


def _head_from(config: dict | None, role: str) -> dict | None:
    if not isinstance(config, dict):
        return None
    models = config.get("models")
    if not isinstance(models, dict):
        return None
    entry = models.get(role)
    if not isinstance(entry, dict) or not entry.get("model"):
        return None
    return {"provider": entry.get("provider") or "anthropic", "model": entry["model"]}


def _resolve_head(
    catalog: list[dict],
    image_config: dict | None,
    agent_overrides: dict | None,
    image_defaults: dict | None,
    *,
    role: str,
    kind: str,
    builtin: dict,
) -> dict:
    """agent override → image config → admin image defaults → catalog default;
    validated to be in-catalog."""
    for src in (agent_overrides, image_config, image_defaults):
        head = _head_from(src, role)
        if head and _in_catalog(catalog, head["provider"], head["model"], kind):
            return head
        if head:
            log.warning(
                "model head %s:%s (%s) not in catalog — falling back to catalog default",
                head["provider"], head["model"], kind,
            )
    return _catalog_default(catalog, kind, builtin)


def resolve_default_heads(
    catalog: list[dict],
    image_config: dict | None,
    agent_overrides: dict | None,
    image_defaults: dict | None = None,
) -> dict:
    """{"primary": {provider, model}, "fast": {provider, model}} — both in-catalog.

    `image_defaults` is the admin-stored overlay (app_settings["image_defaults"]);
    it must be its own source rather than pre-merged into image_config because an
    image's empty models block ({"primary": {}}) would clobber it in a dict merge.
    """
    return {
        "primary": _resolve_head(
            catalog, image_config, agent_overrides, image_defaults,
            role="primary", kind=PRIMARY_KIND, builtin=_BUILTIN_PRIMARY,
        ),
        "fast": _resolve_head(
            catalog, image_config, agent_overrides, image_defaults,
            role="fast", kind=FAST_KIND, builtin=_BUILTIN_FAST,
        ),
    }


def catalog_has(catalog: list[dict], provider: str, model: str) -> bool:
    """True if `model` (id or alias) is an enabled catalog entry for `provider`.
    Used by the proxy wall — kind-agnostic (any purpose counts)."""
    for e in catalog:
        if e["provider"] != provider:
            continue
        if e["model"] == model or model in (e.get("aliases") or []):
            return True
    return False
