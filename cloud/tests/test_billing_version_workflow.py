"""039/002 — version workflow: clone, draft edits, retire, diff, coverage."""

from __future__ import annotations

import pytest

from cloud.billing.seed import commercial_v1_config
from cloud.billing.versions import (
    ConfigValidationError,
    canonical_config_hash,
    clone_version,
    config_diff,
    create_draft_version,
    publish_version,
    retire_version,
    uncovered_gateway_models,
    update_draft,
    validate_commercial_config,
)
from cloud.db.models import GatewayModel

def _valid():
    return commercial_v1_config()


# ── 002 validation rules ─────────────────────────────────────────────────────

def test_model_in_both_tiers_rejected():
    config = _valid()
    config["mid_tier_models"].append(config["top_tier_models"][0])
    with pytest.raises(ConfigValidationError, match="both tiers"):
        validate_commercial_config(config)


def test_unknown_formula_rejected():
    config = _valid()
    for sku in config["skus"]:
        if sku["enabled"]:
            sku["formula"] = "made_up_formula"
            break
    with pytest.raises(ConfigValidationError, match="formula"):
        validate_commercial_config(config)


def test_missing_formula_constant_rejected():
    config = _valid()
    hosting = next(s for s in config["skus"] if s["key"] == "hosting_month")
    hosting["constants"] = {}
    with pytest.raises(ConfigValidationError, match="constant"):
        validate_commercial_config(config)


def test_hosting_price_must_match_sku_constant():
    config = _valid()
    config["hosting"]["price_credits"] = config["hosting"]["price_credits"] + 1
    with pytest.raises(ConfigValidationError, match="hosting"):
        validate_commercial_config(config)


def test_topup_cannot_recur():
    config = _valid()
    for p in config["products"]:
        if p["kind"] == "topup":
            p["interval"] = "month"
    with pytest.raises(ConfigValidationError, match="interval"):
        validate_commercial_config(config)


def test_yearly_lot_math_must_close():
    config = _valid()
    yearly = None
    for p in config["products"]:
        if p["kind"] == "subscription" and p.get("interval") == "year":
            yearly = p
    if yearly is None:  # v1 launches monthly-only; synthesize a yearly product
        monthly = next(p for p in config["products"] if p["kind"] == "subscription")
        yearly = dict(
            monthly,
            key="yearly_test",
            interval="year",
            price_usd_cents=monthly["price_usd_cents"] * 12,
            paid_credits=monthly["paid_credits"] * 12,
            bonus_credits=monthly["bonus_credits"] * 12,
            monthly_paid_lot_credits=monthly["paid_credits"],
            monthly_bonus_lot_credits=monthly["bonus_credits"],
        )
        config["products"].append(yearly)
    validate_commercial_config(config)  # correct lots pass
    yearly["monthly_paid_lot_credits"] += 1
    with pytest.raises(ConfigValidationError, match="12"):
        validate_commercial_config(config)


# ── Draft editing ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_draft_rehashes(db_session):
    draft = await create_draft_version(db_session, name="v1", config=_valid())
    old_hash = draft.config_hash
    config = _valid()
    config["trial"]["gift_credits"] = 2_000
    await update_draft(db_session, draft.id, config=config, name="v1b", notes="bump")
    assert draft.config_hash != old_hash
    assert draft.config_hash == canonical_config_hash(config)
    assert draft.name == "v1b" and draft.notes == "bump"
    await publish_version(db_session, draft.id)  # hash consistent → publishes


@pytest.mark.asyncio
async def test_update_published_version_rejected(db_session):
    version = await create_draft_version(db_session, name="v1", config=_valid())
    await publish_version(db_session, version.id)
    with pytest.raises(ConfigValidationError, match="immutable"):
        await update_draft(db_session, version.id, name="nope")


@pytest.mark.asyncio
async def test_update_draft_validates(db_session):
    draft = await create_draft_version(db_session, name="v1", config=_valid())
    bad = _valid()
    bad["products"] = []
    with pytest.raises(ConfigValidationError):
        await update_draft(db_session, draft.id, config=bad)


# ── Clone ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clone_published_yields_editable_draft(db_session):
    v1 = await create_draft_version(db_session, name="v1", config=_valid())
    await publish_version(db_session, v1.id)
    draft = await clone_version(db_session, v1.id, name="v2-draft")
    assert draft.status == "draft"
    assert draft.parent_version_id == v1.id
    assert draft.version_number == v1.version_number + 1
    assert draft.config_json == v1.config_json
    # Deep copy — editing the clone never touches the published parent.
    config = dict(draft.config_json)
    config["trial"] = dict(config["trial"], gift_credits=2_000)
    await update_draft(db_session, draft.id, config=config)
    parent = v1.config_json
    assert parent["trial"]["gift_credits"] == 1_800


# ── Retire ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retire_lifecycle(db_session):
    v1 = await create_draft_version(db_session, name="v1", config=_valid())
    with pytest.raises(ConfigValidationError, match="cannot retire a draft"):
        await retire_version(db_session, v1.id)
    await publish_version(db_session, v1.id)
    retired = await retire_version(db_session, v1.id)
    assert retired.status == "retired"
    again = await retire_version(db_session, v1.id)  # idempotent
    assert again.status == "retired"
    with pytest.raises(ConfigValidationError):
        await publish_version(db_session, v1.id)  # retired never re-publishes


# ── Diff ─────────────────────────────────────────────────────────────────────

def test_config_diff_flat_paths():
    old = _valid()
    new = _valid()
    new["trial"]["gift_credits"] = 2_000
    new["hosting"]["price_credits"] = 1_099
    diff = config_diff(old, new)
    assert diff["trial.gift_credits"] == {"from": 1_800, "to": 2_000}
    assert "hosting.price_credits" in diff
    assert config_diff(old, _valid()) == {}


# ── Gateway-model coverage ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_rejects_uncovered_enabled_model(db_session):
    db_session.add(GatewayModel(
        provider="anthropic", model="claude-brand-new-model",
        enabled=True, deprecated=False,
    ))
    await db_session.flush()
    draft = await create_draft_version(db_session, name="v1", config=_valid())
    missing = await uncovered_gateway_models(db_session, draft.config_json)
    assert missing == ["claude-brand-new-model"]
    with pytest.raises(ConfigValidationError, match="neither tier"):
        await publish_version(db_session, draft.id)


@pytest.mark.asyncio
async def test_disabled_and_deprecated_models_do_not_block_publish(db_session):
    db_session.add(GatewayModel(
        provider="anthropic", model="old-disabled-model",
        enabled=False, deprecated=False,
    ))
    db_session.add(GatewayModel(
        provider="anthropic", model="old-deprecated-model",
        enabled=True, deprecated=True,
    ))
    await db_session.flush()
    draft = await create_draft_version(db_session, name="v1", config=_valid())
    assert await uncovered_gateway_models(db_session, draft.config_json) == []
    published = await publish_version(db_session, draft.id)
    assert published.status == "published"


@pytest.mark.asyncio
async def test_gateway_model_edits_never_touch_published_config(db_session):
    """The catalog is routing metadata; a published version's economics are
    frozen by hash regardless of catalog edits (039/002)."""
    v1 = await create_draft_version(db_session, name="v1", config=_valid())
    await publish_version(db_session, v1.id)
    frozen_hash = v1.config_hash
    db_session.add(GatewayModel(
        provider="openai", model="gpt-5-new", enabled=True, deprecated=False,
    ))
    await db_session.flush()
    assert v1.config_hash == frozen_hash
    assert v1.config_json == commercial_v1_config()
    # New enabled model only gates FUTURE publishes:
    draft = await clone_version(db_session, v1.id)
    with pytest.raises(ConfigValidationError, match="neither tier"):
        await publish_version(db_session, draft.id)
