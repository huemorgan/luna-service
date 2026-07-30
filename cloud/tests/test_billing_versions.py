"""039/001 — pricing version config: validation, hashing, publish, seeds."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from cloud.billing.models import ProviderCostRate
from cloud.billing.seed import (
    commercial_v1_config,
    seed_billing,
    seed_commercial_v1,
    seed_provider_cost_v1,
)
from cloud.billing.versions import (
    ConfigValidationError,
    assert_mutable,
    canonical_config_hash,
    create_draft_version,
    publish_version,
    validate_commercial_config,
)



def _valid():
    return commercial_v1_config()


# ── Validation ───────────────────────────────────────────────────────────────

def test_launch_config_is_valid():
    validate_commercial_config(_valid())


def test_floats_rejected_anywhere():
    config = _valid()
    config["llm_constants"]["agent"]["top"] = 2.5
    with pytest.raises(ConfigValidationError, match="float"):
        validate_commercial_config(config)
    config = _valid()
    config["products"][0]["price_usd_cents"] = 19.0
    with pytest.raises(ConfigValidationError, match="float"):
        validate_commercial_config(config)


def test_credit_value_fixed():
    config = _valid()
    config["credit_value_micro_usd"] = 20_000
    with pytest.raises(ConfigValidationError, match="fixed"):
        validate_commercial_config(config)


def test_subscription_paid_credits_must_equal_payment():
    config = _valid()
    config["products"][0]["paid_credits"] = 2_000  # hobby_19 pays 1900 cents
    with pytest.raises(ConfigValidationError, match="payment"):
        validate_commercial_config(config)
    # Topups are exempt from the paid==payment invariant but can never carry
    # a bonus (039/002).
    config = _valid()
    for p in config["products"]:
        if p["kind"] == "topup":
            p["bonus_credits"] = 100
    with pytest.raises(ConfigValidationError, match="bonus"):
        validate_commercial_config(config)


def test_duplicate_keys_rejected():
    config = _valid()
    config["skus"].append(dict(config["skus"][0]))
    with pytest.raises(ConfigValidationError, match="duplicate SKU"):
        validate_commercial_config(config)
    config = _valid()
    config["products"].append(dict(config["products"][0]))
    with pytest.raises(ConfigValidationError, match="duplicate product"):
        validate_commercial_config(config)


def test_missing_sections_rejected():
    for key in ("llm_constants", "hosting", "products", "trial", "migration_gift"):
        config = _valid()
        del config[key]
        with pytest.raises(ConfigValidationError):
            validate_commercial_config(config)


def test_canonical_hash_stable_under_key_order():
    a = {"x": 1, "y": {"b": 2, "a": 3}}
    b = {"y": {"a": 3, "b": 2}, "x": 1}
    assert canonical_config_hash(a) == canonical_config_hash(b)


# ── Draft / publish lifecycle ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_draft_publish_lifecycle(db_session):
    v1 = await create_draft_version(db_session, name="v1", config=_valid())
    assert v1.version_number == 1 and v1.status == "draft"
    v2 = await create_draft_version(db_session, name="v2", config=_valid())
    assert v2.version_number == 2

    published = await publish_version(db_session, v1.id)
    assert published.status == "published" and published.published_at is not None
    # Idempotent.
    again = await publish_version(db_session, v1.id)
    assert again.id == v1.id and again.status == "published"
    with pytest.raises(ConfigValidationError, match="immutable"):
        assert_mutable(v1)
    assert_mutable(v2)  # drafts stay editable


@pytest.mark.asyncio
async def test_publish_detects_tampered_draft(db_session):
    version = await create_draft_version(db_session, name="v1", config=_valid())
    tampered = _valid()
    tampered["trial"]["gift_credits"] = 9_999  # still valid — only the hash breaks
    version.config_json = tampered
    with pytest.raises(ConfigValidationError, match="hash mismatch"):
        await publish_version(db_session, version.id)


@pytest.mark.asyncio
async def test_invalid_draft_never_created(db_session):
    config = _valid()
    config["products"] = []
    with pytest.raises(ConfigValidationError):
        await create_draft_version(db_session, name="bad", config=config)


# ── Seeds ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_commercial_v1_idempotent(db_session):
    v1 = await seed_commercial_v1(db_session)
    assert v1.version_number == 1 and v1.status == "published"
    assert v1.config_hash == canonical_config_hash(commercial_v1_config())
    again = await seed_commercial_v1(db_session)
    assert again.id == v1.id


@pytest.mark.asyncio
async def test_seeded_config_contents(db_session):
    v1 = await seed_commercial_v1(db_session)
    config = v1.config_json
    assert config["trial"] == {
        "gift_credits": 1_800, "days": 14,
        "daily_limit_credits": 75, "monthly_limit_credits": 800,
        "active_luna_cap": 1,
    }
    assert config["migration_gift"] == {"credits": 1_800, "days": 28, "active_luna_cap": 1}
    assert config["hosting"]["price_credits"] == 999
    enabled = {s["key"] for s in config["skus"] if s["enabled"]}
    assert enabled == {"llm_call", "image_gen", "voice_session", "hosting_month"}  # everything else fails closed
    product_keys = {p["key"] for p in config["products"]}
    assert {"hobby_19", "recurring_99", "recurring_199", "topup_10"} <= product_keys


@pytest.mark.asyncio
async def test_seed_provider_cost_v1(db_session):
    version = await seed_provider_cost_v1(db_session)
    assert version.version_number == 1 and version.status == "published"
    rates = (
        await db_session.execute(
            select(ProviderCostRate).where(ProviderCostRate.provider_cost_version_id == version.id)
        )
    ).scalars().all()
    assert len(rates) >= 10
    opus_in = next(r for r in rates if r.sku == "claude-opus-4-6" and r.dimension == "input_tokens")
    assert (opus_in.rate_numerator, opus_in.rate_denominator) == (5, 1)  # $5/Mtok
    mini_in = next(r for r in rates if r.sku == "gpt-4o-mini" and r.dimension == "input_tokens")
    assert (mini_in.rate_numerator, mini_in.rate_denominator) == (3, 20)  # $0.15/Mtok
    for r in rates:
        assert r.quality == "estimated" and r.source_url

    again = await seed_provider_cost_v1(db_session)
    assert again.id == version.id
    count = (
        await db_session.execute(select(func.count()).select_from(ProviderCostRate))
    ).scalar_one()
    assert count == len(rates)  # no duplicate rows on reseed


@pytest.mark.asyncio
async def test_seed_billing_runs_both(db_session):
    await seed_billing(db_session)
    await seed_billing(db_session)  # idempotent end-to-end
