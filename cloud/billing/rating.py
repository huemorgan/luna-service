"""Rating: billable usage → one integer credit charge (039/004).

Version resolution is snapshotted at logical-call start:

- the **commercial** version comes from the account's assignment-interval
  chain (`assignments.version_for_account_at`) — the authoritative source,
  never the cached pointer — falling back to the newest published default for
  accounts that predate assignment;
- the **provider-cost** version is the newest published one whose
  `effective_at` is at or before the call start.

Published configs and rate tables are immutable, so both are cached
per-version-id in process. All arithmetic is exact rational micro-USD with a
single final ceil to credits (`cloud/billing/money.py`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import assignments
from cloud.billing.models import (
    CommercialPricingVersion,
    ProviderCostRate,
    ProviderCostVersion,
)
from cloud.billing.money import rate_logical_call_credits, rational_ceil, sum_rationals

# Published versions are immutable — cache configs and rate tables forever.
_CONFIG_CACHE: dict[uuid.UUID, dict] = {}
_RATES_CACHE: dict[uuid.UUID, dict[tuple[str, str, str], tuple[int, int]]] = {}


def invalidate_rating_caches() -> None:
    _CONFIG_CACHE.clear()
    _RATES_CACHE.clear()


class RatingUnavailable(Exception):
    """No published pricing/cost version could be resolved — the billing
    store is unusable for rating (fails closed only in enforce mode)."""


async def resolve_commercial_version(
    session: AsyncSession, account_id: uuid.UUID, at: datetime
) -> tuple[uuid.UUID, dict]:
    """Commercial version + config effective for this account at `at`."""
    version_id = await assignments.version_for_account_at(session, account_id, at)
    if version_id is None:
        # Accounts that predate the assignment hook fall back to the default.
        try:
            version_id = await assignments.default_version_id(session, now=at)
        except Exception as exc:  # noqa: BLE001 — no published version at all
            raise RatingUnavailable(str(exc)) from exc
    config = _CONFIG_CACHE.get(version_id)
    if config is None:
        version = await session.get(CommercialPricingVersion, version_id)
        if version is None or version.config_json is None:
            raise RatingUnavailable(f"commercial version {version_id} not loadable")
        config = version.config_json
        if version.status != "draft":  # drafts are mutable — never cache them
            _CONFIG_CACHE[version_id] = config
    return version_id, config


async def resolve_provider_cost_version(
    session: AsyncSession, at: datetime
) -> uuid.UUID:
    """Newest published provider-cost version effective at `at`."""
    version_id = (
        await session.execute(
            select(ProviderCostVersion.id)
            .where(
                ProviderCostVersion.status == "published",
                ProviderCostVersion.effective_at <= at,
            )
            .order_by(
                ProviderCostVersion.effective_at.desc(),
                ProviderCostVersion.version_number.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if version_id is None:
        raise RatingUnavailable(f"no provider cost version effective at {at.isoformat()}")
    return version_id


async def load_provider_rates(
    session: AsyncSession, version_id: uuid.UUID
) -> dict[tuple[str, str, str], tuple[int, int]]:
    """(provider, model-sku, dimension) → exact rational micro-USD rate."""
    rates = _RATES_CACHE.get(version_id)
    if rates is None:
        rows = (
            await session.execute(
                select(ProviderCostRate).where(
                    ProviderCostRate.provider_cost_version_id == version_id
                )
            )
        ).scalars().all()
        rates = {
            (r.provider, r.sku, r.dimension): (r.rate_numerator, r.rate_denominator)
            for r in rows
        }
        if not rates:
            raise RatingUnavailable(f"provider cost version {version_id} has no rates")
        _RATES_CACHE[version_id] = rates
    return rates


def model_tier(config: dict, model: str | None) -> str | None:
    """Verified tier from the version's explicit lists. None = uncovered
    model — not billable, fails closed as sku_unpriced."""
    if not model:
        return None
    if model in (config.get("top_tier_models") or []):
        return "top"
    if model in (config.get("mid_tier_models") or []):
        return "mid"
    return None


def margin_micro_usd(config: dict, context: str, tier: str) -> int:
    return config["llm_constants"][context][tier]


def sku_enabled(config: dict, sku_key: str | None) -> bool:
    if not sku_key:
        return False
    for sku in config.get("skus") or []:
        if sku.get("key") == sku_key:
            return bool(sku.get("enabled"))
    return False


@dataclass
class AttemptFacts:
    """One provider attempt, normalized by a gateway adapter."""

    provider: str
    model: str | None
    dimensions: dict[str, int]
    billable: bool  # accepted provider work with a successful response
    attempt_number: int = 1
    cost_source: str = "provider_usage"
    provider_request_id: str | None = None
    provider_response_id: str | None = None


@dataclass
class RatingResult:
    vendor_micro_usd: int          # customer-chargeable vendor cost (ceiled)
    margin_micro_usd: int
    credits: int
    rounding_micro_usd: int
    luna_absorbed_micro_usd: int   # failed-attempt provider cost, never charged
    unrated_dimensions: list[str] = field(default_factory=list)
    attempt_costs_micro_usd: list[int] = field(default_factory=list)


def _attempt_parts(
    rates: dict[tuple[str, str, str], tuple[int, int]],
    attempt: AttemptFacts,
) -> tuple[list[tuple[int, int]], list[str]]:
    parts: list[tuple[int, int]] = []
    unrated: list[str] = []
    for dimension, quantity in attempt.dimensions.items():
        if quantity <= 0:
            continue
        rate = rates.get((attempt.provider, attempt.model or "", dimension))
        if rate is None:
            # A dimension without a rate is recorded, never guessed: the
            # vendor total undercounts by that dimension and the gap is
            # visible in the rule snapshot for reconciliation.
            unrated.append(f"{attempt.provider}:{attempt.model}:{dimension}")
            continue
        parts.append((quantity * rate[0], rate[1]))
    return parts, unrated


def rate_call(
    rates: dict[tuple[str, str, str], tuple[int, int]],
    *,
    margin_micro: int,
    attempts: list[AttemptFacts],
) -> RatingResult:
    """Rate one logical call: exact sum of billable attempt costs plus one
    margin, one final ceil. Failed-attempt cost is Luna-absorbed."""
    billable_parts: list[tuple[int, int]] = []
    absorbed_parts: list[tuple[int, int]] = []
    unrated: list[str] = []
    attempt_costs: list[int] = []
    for attempt in attempts:
        parts, missing = _attempt_parts(rates, attempt)
        unrated.extend(missing)
        num, den = sum_rationals(parts) if parts else (0, 1)
        attempt_costs.append(rational_ceil(num, den))
        (billable_parts if attempt.billable else absorbed_parts).extend(parts)

    vendor_micro, credits = rate_logical_call_credits(
        billable_parts or [(0, 1)], margin_micro
    )
    absorbed_num, absorbed_den = sum_rationals(absorbed_parts) if absorbed_parts else (0, 1)
    return RatingResult(
        vendor_micro_usd=vendor_micro,
        margin_micro_usd=margin_micro,
        credits=credits,
        rounding_micro_usd=credits * 10_000 - vendor_micro - margin_micro,
        luna_absorbed_micro_usd=rational_ceil(absorbed_num, absorbed_den),
        unrated_dimensions=unrated,
        attempt_costs_micro_usd=attempt_costs,
    )


def estimate_credits(
    rates: dict[tuple[str, str, str], tuple[int, int]],
    *,
    provider: str,
    model: str,
    dimensions: dict[str, int],
    margin_micro: int,
) -> int:
    """Pre-flight hold size for the estimated dimensions under the same
    snapshotted tariff used at settlement."""
    parts, _ = _attempt_parts(
        rates,
        AttemptFacts(provider=provider, model=model, dimensions=dimensions, billable=True),
    )
    _, credits = rate_logical_call_credits(parts or [(0, 1)], margin_micro)
    return credits
