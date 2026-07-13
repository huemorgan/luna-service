"""Commercial pricing version config: validation, canonical hash, publish.

`config_json` schema version 1 (all money values integer micro-USD or integer
credits; never floats — decimal strings are converted by admin routes before
reaching here):

{
  "credit_value_micro_usd": 10000,            # read-only, fixed
  "llm_constants": {                          # fixed margin per logical call
    "agent":  {"top": 20000, "mid": 10000},   # micro-USD
    "direct": {"top": 10000, "mid": 5000},
    "forge":  {"top": 50000, "mid": 50000}
  },
  "top_tier_models": ["claude-opus-4-6", ...],  # explicit list; others are mid
  "skus": [{"key": ..., "service": ..., "formula": ..., "constants": {...},
             "enabled": bool}, ...],
  "hosting": {"price_credits": 999, "period": "monthly_anchor"},
  "products": [{"key": ..., "kind": "subscription|topup",
                 "interval": "month|year|null", "price_usd_cents": int,
                 "paid_credits": int, "bonus_credits": int,
                 "yearly_gift_credits": int, "expiration": ...}, ...],
  "trial": {"gift_credits": 1800, "days": 28,
             "daily_limit_credits": 75, "monthly_limit_credits": 800,
             "active_luna_cap": 1},
  "migration_gift": {"credits": 1800, "days": 28},   # M9: trial treatment
  "gift_default_days": 90,
  "topup_steps_usd_cents": [1000, 2500, 5000, 10000]
}
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing.models import CommercialPricingVersion, ProviderCostVersion

CONFIG_SCHEMA_VERSION = 1
CONTEXTS = ("agent", "direct", "forge")
TIERS = ("top", "mid")


class ConfigValidationError(ValueError):
    pass


def _require_int(value, path: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigValidationError(f"{path} must be an integer, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise ConfigValidationError(f"{path} must be >= {minimum}")
    return value


def _reject_floats(value, path: str) -> None:
    if isinstance(value, float):
        raise ConfigValidationError(f"{path} is a float — financial config must be integer/string")
    if isinstance(value, dict):
        for k, v in value.items():
            _reject_floats(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _reject_floats(v, f"{path}[{i}]")


def canonical_config_hash(config: dict) -> str:
    blob = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def validate_commercial_config(config: dict) -> None:
    """Validate economics only — Stripe bindings are deliberately NOT
    required here (publication is decoupled from Stripe; bindings gate
    environment activation and checkout in 039/006-007)."""
    _reject_floats(config, "config")

    if config.get("credit_value_micro_usd") != 10_000:
        raise ConfigValidationError("credit_value_micro_usd is fixed at 10000")

    llm = config.get("llm_constants")
    if not isinstance(llm, dict):
        raise ConfigValidationError("llm_constants missing")
    for ctx in CONTEXTS:
        tiers = llm.get(ctx)
        if not isinstance(tiers, dict):
            raise ConfigValidationError(f"llm_constants.{ctx} missing")
        for tier in TIERS:
            _require_int(tiers.get(tier), f"llm_constants.{ctx}.{tier}", minimum=0)

    top_models = config.get("top_tier_models")
    if not isinstance(top_models, list) or not all(isinstance(m, str) for m in top_models):
        raise ConfigValidationError("top_tier_models must be a list of model IDs")

    skus = config.get("skus")
    if not isinstance(skus, list):
        raise ConfigValidationError("skus must be a list")
    seen_keys = set()
    for i, sku in enumerate(skus):
        for field in ("key", "service", "formula"):
            if not isinstance(sku.get(field), str) or not sku[field]:
                raise ConfigValidationError(f"skus[{i}].{field} missing")
        if not isinstance(sku.get("enabled"), bool):
            raise ConfigValidationError(f"skus[{i}].enabled must be a bool")
        if sku["key"] in seen_keys:
            raise ConfigValidationError(f"duplicate SKU key {sku['key']!r}")
        seen_keys.add(sku["key"])

    hosting = config.get("hosting")
    if not isinstance(hosting, dict):
        raise ConfigValidationError("hosting missing")
    _require_int(hosting.get("price_credits"), "hosting.price_credits", minimum=1)

    products = config.get("products")
    if not isinstance(products, list) or not products:
        raise ConfigValidationError("products must be a non-empty list")
    seen_products = set()
    for i, product in enumerate(products):
        key = product.get("key")
        if not isinstance(key, str) or not key:
            raise ConfigValidationError(f"products[{i}].key missing")
        if key in seen_products:
            raise ConfigValidationError(f"duplicate product key {key!r}")
        seen_products.add(key)
        if product.get("kind") not in ("subscription", "topup"):
            raise ConfigValidationError(f"products[{i}].kind must be subscription|topup")
        _require_int(product.get("price_usd_cents"), f"products[{i}].price_usd_cents", minimum=0)
        paid = _require_int(product.get("paid_credits"), f"products[{i}].paid_credits", minimum=0)
        _require_int(product.get("bonus_credits", 0), f"products[{i}].bonus_credits", minimum=0)
        if product["kind"] == "subscription":
            if product.get("interval") not in ("month", "year"):
                raise ConfigValidationError(f"products[{i}].interval must be month|year")
            # Paid credits always equal payment × 100 (no dollar discounts).
            if paid != product["price_usd_cents"]:
                raise ConfigValidationError(
                    f"products[{i}]: paid_credits {paid} != price_usd_cents "
                    f"{product['price_usd_cents']} (1 credit = $0.01, paid = payment × 100)"
                )

    trial = config.get("trial")
    if not isinstance(trial, dict):
        raise ConfigValidationError("trial missing")
    _require_int(trial.get("gift_credits"), "trial.gift_credits", minimum=0)
    _require_int(trial.get("days"), "trial.days", minimum=1)

    migration = config.get("migration_gift")
    if not isinstance(migration, dict):
        raise ConfigValidationError("migration_gift missing")
    _require_int(migration.get("credits"), "migration_gift.credits", minimum=0)
    _require_int(migration.get("days"), "migration_gift.days", minimum=1)

    steps = config.get("topup_steps_usd_cents")
    if not isinstance(steps, list) or not all(
        isinstance(s, int) and not isinstance(s, bool) and s > 0 for s in steps
    ):
        raise ConfigValidationError("topup_steps_usd_cents must be positive integers")


async def create_draft_version(
    session: AsyncSession,
    *,
    name: str,
    config: dict,
    created_by: uuid.UUID | None = None,
    parent_version_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> CommercialPricingVersion:
    validate_commercial_config(config)
    max_number = (
        await session.execute(select(func.coalesce(func.max(CommercialPricingVersion.version_number), 0)))
    ).scalar_one()
    version = CommercialPricingVersion(
        version_number=max_number + 1,
        name=name,
        status="draft",
        parent_version_id=parent_version_id,
        config_json=config,
        config_schema_version=CONFIG_SCHEMA_VERSION,
        config_hash=canonical_config_hash(config),
        notes=notes,
        created_by=created_by,
    )
    session.add(version)
    await session.flush()
    return version


async def publish_version(
    session: AsyncSession, version_id: uuid.UUID, *, now: datetime | None = None
) -> CommercialPricingVersion:
    """Publish validates economics only. Stripe bindings gate activation for
    checkout, not publication. Published versions are immutable forever."""
    version = await session.get(CommercialPricingVersion, version_id)
    if version is None:
        raise ConfigValidationError("version not found")
    if version.status == "published":
        return version
    if version.status != "draft":
        raise ConfigValidationError(f"cannot publish a {version.status} version")
    validate_commercial_config(version.config_json)
    if canonical_config_hash(version.config_json) != version.config_hash:
        raise ConfigValidationError("config hash mismatch — draft was tampered with")
    version.status = "published"
    version.published_at = now or datetime.now(timezone.utc)
    await session.flush()
    return version


def assert_mutable(version: CommercialPricingVersion | ProviderCostVersion) -> None:
    """Service-level guard mirroring the DB trigger: published/retired
    versions never change financial fields."""
    if version.status != "draft":
        raise ConfigValidationError(f"{version.status} versions are immutable")
