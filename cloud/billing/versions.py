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
  "top_tier_models": ["claude-opus-4-6", ...],  # explicit lists; a model in
  "mid_tier_models": ["gpt-4o", ...],           # neither is NOT billable
                                                # (fails closed, sku_unpriced)
  "skus": [{"key": ..., "service": ..., "formula": ..., "constants": {...},
             "enabled": bool}, ...],
  "hosting": {"price_credits": 999, "period": "monthly_anchor"},
  "products": [{"key": ..., "kind": "subscription|topup",
                 "interval": "month|year|null", "price_usd_cents": int,
                 "paid_credits": int, "bonus_credits": int,
                 "yearly_gift_credits": int, "expiration": ...}, ...],
  "trial": {"gift_credits": 1800, "days": 28,
             "daily_limit_credits": 75, "monthly_limit_credits": 800,
             "active_luna_cap": 1,
             # optional partner signup offers by verified email domain;
             # replaces the standard gift (days falls back to trial.days)
             "domain_gifts": {"monday.com": {"gift_credits": 20000}}},
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

# Every SKU formula must be one of these — an unknown formula string could
# encode a rule the raters don't bound, so it is rejected at validation.
# Per-formula required integer constants (all >= 0):
FORMULA_CONSTANTS: dict[str, tuple[str, ...]] = {
    "vendor_plus_context_constant": (),  # margin comes from llm_constants
    "fixed_credits": ("price_credits",),
    "per_request_constant": ("credits_per_request",),
    "per_unit_constant": ("credits_per_unit",),
}


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
    mid_models = config.get("mid_tier_models", [])
    if not isinstance(mid_models, list) or not all(isinstance(m, str) for m in mid_models):
        raise ConfigValidationError("mid_tier_models must be a list of model IDs")
    both = set(top_models) & set(mid_models)
    if both:
        raise ConfigValidationError(f"models in both tiers: {sorted(both)}")

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
        formula = sku["formula"]
        if formula not in FORMULA_CONSTANTS:
            raise ConfigValidationError(f"skus[{i}].formula {formula!r} unknown")
        if sku["enabled"]:
            # An enabled SKU must have a complete nonnegative rule; disabled
            # SKUs are catalog placeholders and fail closed at rating.
            constants = sku.get("constants")
            if not isinstance(constants, dict):
                raise ConfigValidationError(f"skus[{i}].constants missing")
            for name in FORMULA_CONSTANTS[formula]:
                _require_int(constants.get(name), f"skus[{i}].constants.{name}", minimum=0)

    hosting = config.get("hosting")
    if not isinstance(hosting, dict):
        raise ConfigValidationError("hosting missing")
    _require_int(hosting.get("price_credits"), "hosting.price_credits", minimum=1)
    for sku in skus:
        if sku["key"] == "hosting_month" and sku["enabled"]:
            if sku["constants"].get("price_credits") != hosting["price_credits"]:
                raise ConfigValidationError(
                    "hosting.price_credits and the hosting_month SKU constant disagree"
                )

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
        bonus = _require_int(product.get("bonus_credits", 0), f"products[{i}].bonus_credits", minimum=0)
        if product["kind"] == "topup":
            # Top-ups are pure credit purchases: no bonus, no gift, no interval.
            if bonus != 0:
                raise ConfigValidationError(f"products[{i}]: top-ups cannot carry a bonus")
            if product.get("yearly_gift_credits", 0) != 0:
                raise ConfigValidationError(f"products[{i}]: top-ups cannot carry a yearly gift")
            if product.get("interval") is not None:
                raise ConfigValidationError(f"products[{i}]: top-ups have no interval")
        if product["kind"] == "subscription":
            if product.get("interval") not in ("month", "year"):
                raise ConfigValidationError(f"products[{i}].interval must be month|year")
            # Paid credits always equal payment × 100 (no dollar discounts).
            if paid != product["price_usd_cents"]:
                raise ConfigValidationError(
                    f"products[{i}]: paid_credits {paid} != price_usd_cents "
                    f"{product['price_usd_cents']} (1 credit = $0.01, paid = payment × 100)"
                )
            _require_int(product.get("yearly_gift_credits", 0),
                         f"products[{i}].yearly_gift_credits", minimum=0)
            if product["interval"] == "year":
                # Yearly buckets are 12 scheduled monthly lots; the lot sizes
                # must reconstruct the totals exactly.
                lot_paid = _require_int(product.get("monthly_paid_lot_credits"),
                                        f"products[{i}].monthly_paid_lot_credits", minimum=0)
                lot_bonus = _require_int(product.get("monthly_bonus_lot_credits", 0),
                                         f"products[{i}].monthly_bonus_lot_credits", minimum=0)
                if lot_paid * 12 != paid:
                    raise ConfigValidationError(
                        f"products[{i}]: monthly_paid_lot_credits × 12 != paid_credits"
                    )
                if lot_bonus * 12 != bonus:
                    raise ConfigValidationError(
                        f"products[{i}]: monthly_bonus_lot_credits × 12 != bonus_credits"
                    )

    trial = config.get("trial")
    if not isinstance(trial, dict):
        raise ConfigValidationError("trial missing")
    _require_int(trial.get("gift_credits"), "trial.gift_credits", minimum=0)
    _require_int(trial.get("days"), "trial.days", minimum=1)

    domain_gifts = trial.get("domain_gifts")
    if domain_gifts is not None:
        if not isinstance(domain_gifts, dict):
            raise ConfigValidationError("trial.domain_gifts must be a map of email domain -> gift")
        for dom, gift in domain_gifts.items():
            if not isinstance(dom, str) or not dom or "@" in dom or dom != dom.lower():
                raise ConfigValidationError(
                    f"trial.domain_gifts key {dom!r} must be a lowercase email domain"
                )
            if not isinstance(gift, dict):
                raise ConfigValidationError(f"trial.domain_gifts.{dom} must be an object")
            _require_int(gift.get("gift_credits"), f"trial.domain_gifts.{dom}.gift_credits", minimum=0)
            if gift.get("days") is not None:
                _require_int(gift.get("days"), f"trial.domain_gifts.{dom}.days", minimum=1)

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


async def uncovered_gateway_models(session: AsyncSession, config: dict) -> list[str]:
    """Enabled, non-deprecated gateway models missing from both tier lists.

    `gateway_models` is routing/catalog metadata — this is a publish-time
    completeness check only; rating never reads that table. A model in
    neither list fails closed (`sku_unpriced`) at rating time.
    """
    from cloud.db.models import GatewayModel

    covered = set(config.get("top_tier_models", [])) | set(config.get("mid_tier_models", []))
    rows = (
        await session.execute(
            select(GatewayModel.model).where(
                GatewayModel.enabled.is_(True), GatewayModel.deprecated.is_(False)
            )
        )
    ).scalars().all()
    return sorted(set(rows) - covered)


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
    uncovered = await uncovered_gateway_models(session, version.config_json)
    if uncovered:
        raise ConfigValidationError(
            f"enabled gateway models in neither tier list: {uncovered}"
        )
    version.status = "published"
    version.published_at = now or datetime.now(timezone.utc)
    await session.flush()
    return version


async def update_draft(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    config: dict | None = None,
    name: str | None = None,
    notes: str | None = None,
) -> CommercialPricingVersion:
    """Edit a draft in place. Published/retired versions never change."""
    version = await session.get(CommercialPricingVersion, version_id)
    if version is None:
        raise ConfigValidationError("version not found")
    assert_mutable(version)
    if config is not None:
        validate_commercial_config(config)
        version.config_json = config
        version.config_hash = canonical_config_hash(config)
    if name is not None:
        version.name = name
    if notes is not None:
        version.notes = notes
    await session.flush()
    return version


async def clone_version(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    name: str | None = None,
    created_by: uuid.UUID | None = None,
    notes: str | None = None,
) -> CommercialPricingVersion:
    """Clone any version into a fresh draft (the only way to derive a new
    version from a published one)."""
    source = await session.get(CommercialPricingVersion, version_id)
    if source is None:
        raise ConfigValidationError("version not found")
    return await create_draft_version(
        session,
        name=name or f"{source.name} (copy)",
        config=json.loads(json.dumps(source.config_json)),
        created_by=created_by,
        parent_version_id=source.id,
        notes=notes,
    )


async def retire_version(session: AsyncSession, version_id: uuid.UUID) -> CommercialPricingVersion:
    """published → retired is the only allowed post-publication transition."""
    version = await session.get(CommercialPricingVersion, version_id)
    if version is None:
        raise ConfigValidationError("version not found")
    if version.status == "retired":
        return version
    if version.status != "published":
        raise ConfigValidationError(f"cannot retire a {version.status} version")
    version.status = "retired"
    await session.flush()
    return version


def config_diff(old: dict, new: dict, path: str = "") -> dict[str, dict]:
    """Flat {json.path: {"from": ..., "to": ...}} diff for the admin UI."""
    diff: dict[str, dict] = {}
    keys = set(old) | set(new) if isinstance(old, dict) and isinstance(new, dict) else set()
    if keys:
        for key in sorted(keys):
            sub_path = f"{path}.{key}" if path else str(key)
            if key not in old:
                diff[sub_path] = {"from": None, "to": new[key]}
            elif key not in new:
                diff[sub_path] = {"from": old[key], "to": None}
            elif old[key] != new[key]:
                if isinstance(old[key], dict) and isinstance(new[key], dict):
                    diff.update(config_diff(old[key], new[key], sub_path))
                else:
                    diff[sub_path] = {"from": old[key], "to": new[key]}
    elif old != new:
        diff[path or "config"] = {"from": old, "to": new}
    return diff


def assert_mutable(version: CommercialPricingVersion | ProviderCostVersion) -> None:
    """Service-level guard mirroring the DB trigger: published/retired
    versions never change financial fields."""
    if version.status != "draft":
        raise ConfigValidationError(f"{version.status} versions are immutable")


# ── Provider-cost versions (global, effective-dated, never cohort-pinned) ────

def provider_rates_hash(rates: list[dict]) -> str:
    blob = json.dumps(sorted(rates, key=lambda r: (r["provider"], r["sku"], r["dimension"])),
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


async def create_provider_cost_draft(
    session: AsyncSession,
    *,
    rates: list[dict],
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> ProviderCostVersion:
    from cloud.billing.models import ProviderCostRate

    if not rates:
        raise ConfigValidationError("rates must be non-empty")
    seen = set()
    for i, rate in enumerate(rates):
        for field in ("provider", "sku", "dimension", "unit"):
            if not isinstance(rate.get(field), str) or not rate[field]:
                raise ConfigValidationError(f"rates[{i}].{field} missing")
        _require_int(rate.get("rate_numerator"), f"rates[{i}].rate_numerator", minimum=0)
        _require_int(rate.get("rate_denominator"), f"rates[{i}].rate_denominator", minimum=1)
        key = (rate["provider"], rate["sku"], rate["dimension"])
        if key in seen:
            raise ConfigValidationError(f"duplicate rate for {key}")
        seen.add(key)

    max_number = (
        await session.execute(select(func.coalesce(func.max(ProviderCostVersion.version_number), 0)))
    ).scalar_one()
    version = ProviderCostVersion(
        version_number=max_number + 1,
        status="draft",
        config_hash=provider_rates_hash(rates),
        notes=notes,
        created_by=created_by,
    )
    session.add(version)
    await session.flush()
    for rate in rates:
        session.add(ProviderCostRate(
            provider_cost_version_id=version.id,
            provider=rate["provider"],
            sku=rate["sku"],
            dimension=rate["dimension"],
            unit=rate["unit"],
            rate_numerator=rate["rate_numerator"],
            rate_denominator=rate["rate_denominator"],
            quality=rate.get("quality", "estimated"),
            source_url=rate.get("source_url"),
        ))
    await session.flush()
    return version


async def publish_provider_cost_version(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    effective_at: datetime,
    now: datetime | None = None,
) -> ProviderCostVersion:
    """Provider-cost publication is global and effective-dated. There is
    deliberately no account/cohort parameter — costs can never be pinned to
    a customer cohort."""
    version = await session.get(ProviderCostVersion, version_id)
    if version is None:
        raise ConfigValidationError("provider-cost version not found")
    if version.status == "published":
        return version
    if version.status != "draft":
        raise ConfigValidationError(f"cannot publish a {version.status} version")
    version.status = "published"
    version.effective_at = effective_at
    version.published_at = now or datetime.now(timezone.utc)
    await session.flush()
    return version
