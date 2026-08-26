"""Seed commercial pricing version 1 and provider-cost version 1 (039/001).

Idempotent: re-running never duplicates or mutates a published version.
All values are the parent plan's launch defaults; later economics changes are
new versions, never edits.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing.models import CommercialPricingVersion, ProviderCostRate, ProviderCostVersion
from cloud.billing.provider_rates_v1 import PROVIDER_RATES_V1, RETRIEVED_AT
from cloud.billing.versions import (
    canonical_config_hash,
    create_draft_version,
    publish_version,
    validate_commercial_config,
)


def commercial_v1_config() -> dict:
    """Launch defaults from plans/039-pricing-billing/PLAN.md."""
    return {
        "credit_value_micro_usd": 10_000,
        "llm_constants": {
            # Fixed margin micro-USD per logical call, by context and verified
            # model tier. Internal-only; never exposed to customers or agents.
            "agent": {"top": 20_000, "mid": 10_000},
            "direct": {"top": 10_000, "mid": 5_000},
            "forge": {"top": 50_000, "mid": 50_000},
        },
        # Tier is a capability judgment (frontier vs workhorse), not a vendor
        # cost bracket: grok-4.5 and gpt-5.5 are flagship reasoning models even
        # though their token rates sit at or below sonnet's.
        "top_tier_models": [
            "claude-opus-4-6", "gpt-5.5", "grok-4.5", "kimi-k3",
            # OpenAI Realtime voice (flagship voice model — tier is capability,
            # not token price). Billed per session via the voice_session SKU.
            # Exact API model id as sent by plugin-voice — coverage is an
            # exact-string match, so this must track the client's model name.
            "gpt-realtime-2.1",
            "gpt-4o-realtime-preview",
            # 070: Qwen flagship (preview) — frontier agentic reasoning at a
            # bargain token rate; tier is capability, not price.
            "qwen3.8-max",
        ],
        # Explicit coverage: a model in neither list is not billable (fails
        # closed at rating). Publish rejects uncovered enabled gateway models.
        "mid_tier_models": [
            "claude-sonnet-4-5-20250929",
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-20250514",  # deprecated but still enabled in the catalog
            "gpt-4o",
            "gpt-4o-mini",
            "text-embedding-3-small",
            "text-embedding-3-large",
            "grok-4.3",
            "grok-build-0.1",
            "kimi-k2.7-code",
            # 063: agent-ops workhorse — frontier-adjacent but priced and
            # positioned as the operational core, not the flagship (K3 is).
            "kimi-k2.6",
            # 070: Qwen workhorses — agentic coder + cheap fast tier.
            "qwen3-coder-next",
            "qwen3.7-flash",
            # Image-generation models (041) — margin llm_constants[context][mid].
            "gemini-3-pro-image",
            "gemini-2.5-flash-image",
            "gpt-image-1",  # deprecated upstream, retires 2026-10-23
            "gpt-image-1.5",
            "gpt-image-1-mini",
            # Realtime voice workhorse variants.
            "gpt-realtime-2.1-mini",
            "gpt-4o-mini-realtime-preview",
        ],
        "skus": [
            {"key": "llm_call", "service": "llm", "formula": "vendor_plus_context_constant",
             "constants": {}, "enabled": True},
            {"key": "image_gen", "service": "image", "formula": "vendor_plus_context_constant",
             "constants": {}, "enabled": True},
            # Realtime voice: flat per-session vendor estimate (the audio
            # bypasses the gateway — see route_catalog) + context margin.
            {"key": "voice_session", "service": "voice", "formula": "vendor_plus_context_constant",
             "constants": {}, "enabled": True},
            {"key": "hosting_month", "service": "hosting", "formula": "fixed_credits",
             "constants": {"price_credits": 999}, "enabled": True},
            # Non-LLM services: seeded in the catalog, disabled until each
            # receives a defined price. Disabled SKUs fail closed in enforce.
            {"key": "search_request", "service": "search", "formula": "per_request_constant",
             "constants": {}, "enabled": False},
            {"key": "browser_request", "service": "browser", "formula": "per_request_constant",
             "constants": {}, "enabled": False},
            {"key": "composio_request", "service": "composio", "formula": "per_request_constant",
             "constants": {}, "enabled": False},
            {"key": "storage_gb_month", "service": "storage", "formula": "per_unit_constant",
             "constants": {}, "enabled": False},
            {"key": "forge_machine_minute", "service": "forge", "formula": "per_unit_constant",
             "constants": {}, "enabled": False},
            {"key": "forge_llm_call", "service": "forge", "formula": "vendor_plus_context_constant",
             "constants": {}, "enabled": False},
            {"key": "marketplace_item", "service": "marketplace", "formula": "fixed_credits",
             "constants": {}, "enabled": False},
        ],
        "hosting": {"price_credits": 999, "period": "monthly_anchor"},
        "products": [
            {"key": "hobby_19", "kind": "subscription", "interval": "month",
             "price_usd_cents": 1_900, "paid_credits": 1_900, "bonus_credits": 0,
             "yearly_gift_credits": 0},
            # Tier totals stay at 11,000 / 25,000 credits; the $99/$199 price
            # points shrink the paid part so the bonus absorbs the difference.
            {"key": "recurring_99", "kind": "subscription", "interval": "month",
             "price_usd_cents": 9_900, "paid_credits": 9_900, "bonus_credits": 1_100,
             "yearly_gift_credits": 0},
            {"key": "recurring_199", "kind": "subscription", "interval": "month",
             "price_usd_cents": 19_900, "paid_credits": 19_900, "bonus_credits": 5_100,
             "yearly_gift_credits": 0},
            # Yearly: price = 12× monthly, paid credits = payment × 100 split
            # into 12 scheduled monthly lots; incentive is the yearly gift lot
            # worth two months of the package's paid monthly credits.
            {"key": "hobby_19_yearly", "kind": "subscription", "interval": "year",
             "price_usd_cents": 22_800, "paid_credits": 22_800, "bonus_credits": 0,
             "monthly_paid_lot_credits": 1_900, "monthly_bonus_lot_credits": 0,
             "yearly_gift_credits": 3_800},
            {"key": "recurring_99_yearly", "kind": "subscription", "interval": "year",
             "price_usd_cents": 118_800, "paid_credits": 118_800, "bonus_credits": 13_200,
             "monthly_paid_lot_credits": 9_900, "monthly_bonus_lot_credits": 1_100,
             "yearly_gift_credits": 19_800},
            {"key": "recurring_199_yearly", "kind": "subscription", "interval": "year",
             "price_usd_cents": 238_800, "paid_credits": 238_800, "bonus_credits": 61_200,
             "monthly_paid_lot_credits": 19_900, "monthly_bonus_lot_credits": 5_100,
             "yearly_gift_credits": 39_800},
            {"key": "topup_10", "kind": "topup", "interval": None,
             "price_usd_cents": 1_000, "paid_credits": 1_000, "bonus_credits": 0},
            {"key": "topup_25", "kind": "topup", "interval": None,
             "price_usd_cents": 2_500, "paid_credits": 2_500, "bonus_credits": 0},
            {"key": "topup_50", "kind": "topup", "interval": None,
             "price_usd_cents": 5_000, "paid_credits": 5_000, "bonus_credits": 0},
            {"key": "topup_100", "kind": "topup", "interval": None,
             "price_usd_cents": 10_000, "paid_credits": 10_000, "bonus_credits": 0},
        ],
        "trial": {
            "gift_credits": 1_800, "days": 14,
            "daily_limit_credits": 75, "monthly_limit_credits": 800,
            "active_luna_cap": 1,
            # Partner signup offers by verified email domain — replaces the
            # standard gift for matching signups ($200; days falls back to
            # trial.days when unset).
            "domain_gifts": {"monday.com": {"gift_credits": 20_000}},
        },
        # M9 (owner decision): migrated accounts get exactly the trial
        # treatment — configurable here like every other product.
        "migration_gift": {"credits": 1_800, "days": 28, "active_luna_cap": 1},
        "gift_default_days": 90,
        "topup_steps_usd_cents": [1_000, 2_500, 5_000, 10_000],
    }


def provider_v1_hash() -> str:
    blob = json.dumps(
        {"retrieved_at": RETRIEVED_AT, "rates": PROVIDER_RATES_V1},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


async def seed_commercial_v1(session: AsyncSession) -> CommercialPricingVersion:
    existing = (
        await session.execute(
            select(CommercialPricingVersion).where(CommercialPricingVersion.version_number == 1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    config = commercial_v1_config()
    validate_commercial_config(config)
    version = await create_draft_version(session, name="Launch defaults v1", config=config,
                                         notes="Seeded by 039/001 from parent-plan defaults")
    assert version.config_hash == canonical_config_hash(config)
    await publish_version(session, version.id)
    return version


async def seed_provider_cost_v1(session: AsyncSession) -> ProviderCostVersion:
    existing = (
        await session.execute(
            select(ProviderCostVersion).where(ProviderCostVersion.version_number == 1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    now = datetime.now(timezone.utc)
    retrieved = datetime.fromisoformat(RETRIEVED_AT).replace(tzinfo=timezone.utc)
    version = ProviderCostVersion(
        version_number=1,
        status="published",
        effective_at=now,
        published_at=now,
        config_hash=provider_v1_hash(),
        notes="Seeded by 039/001 from cloud/billing/provider_rates_v1.py",
    )
    session.add(version)
    await session.flush()
    for provider, sku, dimension, unit, num, den, source_url in PROVIDER_RATES_V1:
        session.add(
            ProviderCostRate(
                provider_cost_version_id=version.id,
                provider=provider,
                sku=sku,
                dimension=dimension,
                unit=unit,
                rate_numerator=num,
                rate_denominator=den,
                quality="estimated",
                source_url=source_url,
                retrieved_at=retrieved,
            )
        )
    await session.flush()
    return version


async def seed_billing(session: AsyncSession) -> None:
    await seed_commercial_v1(session)
    await seed_provider_cost_v1(session)
