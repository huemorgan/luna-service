"""Plan 018 — model catalog resolver + seed tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cloud.db.models import GatewayModel
from cloud.gateway.model_registry import SEED_MODELS, seed_models
from cloud.provisioning.model_catalog import (
    catalog_has,
    resolve_default_heads,
    system_catalog,
)

pytestmark = pytest.mark.asyncio


# ── system_catalog + seed ────────────────────────────────────────────────────

async def test_seed_models_idempotent(db_session):
    await seed_models(db_session)
    await db_session.commit()
    rows = (await db_session.execute(select(GatewayModel))).scalars().all()
    assert len(rows) == len(SEED_MODELS)

    # Second run adds nothing and doesn't clobber an edit.
    opus = next(r for r in rows if r.model == "claude-opus-4-6")
    opus.label = "Edited"
    await db_session.commit()
    await seed_models(db_session)
    await db_session.commit()
    rows2 = (await db_session.execute(select(GatewayModel))).scalars().all()
    assert len(rows2) == len(SEED_MODELS)
    assert next(r for r in rows2 if r.model == "claude-opus-4-6").label == "Edited"


async def test_system_catalog_only_enabled_and_shape(db_session):
    await seed_models(db_session)
    # Disable one.
    row = (await db_session.execute(
        select(GatewayModel).where(GatewayModel.model == "gpt-4o-mini")
    )).scalar_one()
    row.enabled = False
    await db_session.commit()

    catalog = await system_catalog(db_session)
    models = {e["model"] for e in catalog}
    assert "gpt-4o-mini" not in models
    assert "claude-opus-4-6" in models

    opus = next(e for e in catalog if e["model"] == "claude-opus-4-6")
    assert opus["provider"] == "anthropic"
    assert "reasoning" in opus["kinds"]
    # 063: opus no longer carries the recommended flag.
    assert opus.get("recommended_default") is not True
    assert "opus" in opus.get("aliases", [])


async def test_system_catalog_has_kimi_models(db_session):
    await seed_models(db_session)
    catalog = await system_catalog(db_session)
    k3 = next(e for e in catalog if e["model"] == "kimi-k3")
    assert k3["provider"] == "moonshot"
    assert "reasoning" in k3["kinds"]
    assert "kimi" in k3.get("aliases", [])
    k27 = next(e for e in catalog if e["model"] == "kimi-k2.7-code")
    assert k27["provider"] == "moonshot"
    k26 = next(e for e in catalog if e["model"] == "kimi-k2.6")
    assert k26["label"] == "Kimi K2.6 Agent Ops"
    assert "kimi-agent-ops" in k26.get("aliases", [])


async def test_system_catalog_has_no_invented_ids(db_session):
    await seed_models(db_session)
    await db_session.commit()
    catalog = await system_catalog(db_session)
    ids = {e["model"] for e in catalog}
    # Invented / never-served ids must be absent.
    for stale in ("o3", "o4-mini", "gpt-4-turbo", "claude-opus-4-20250514",
                  "claude-sonnet-4-20250514"):
        assert stale not in ids


# ── resolve_default_heads ────────────────────────────────────────────────────

async def test_heads_default_to_catalog_recommended(db_session):
    await seed_models(db_session)
    await db_session.commit()
    catalog = await system_catalog(db_session)
    heads = resolve_default_heads(catalog, image_config={"models": {}}, agent_overrides=None)
    assert heads["primary"] == {"provider": "anthropic", "model": "claude-opus-4-6"}
    assert heads["fast"] == {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}


async def test_image_overrides_catalog_default(db_session):
    await seed_models(db_session)
    await db_session.commit()
    catalog = await system_catalog(db_session)
    img = {"models": {"primary": {"provider": "openai", "model": "gpt-4o"}}}
    heads = resolve_default_heads(catalog, image_config=img, agent_overrides=None)
    assert heads["primary"] == {"provider": "openai", "model": "gpt-4o"}
    # fast falls through to the catalog default.
    assert heads["fast"]["model"] == "claude-haiku-4-5-20251001"


async def test_agent_override_beats_image(db_session):
    await seed_models(db_session)
    await db_session.commit()
    catalog = await system_catalog(db_session)
    img = {"models": {"primary": {"provider": "openai", "model": "gpt-4o"}}}
    ov = {"models": {"primary": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"}}}
    heads = resolve_default_heads(catalog, image_config=img, agent_overrides=ov)
    assert heads["primary"]["model"] == "claude-sonnet-4-5-20250929"


async def test_offcatalog_head_falls_back_to_catalog_default(db_session):
    """A head pinned to a model that isn't in the catalog (the brick scenario)
    self-heals to the catalog default rather than bricking."""
    await seed_models(db_session)
    await db_session.commit()
    catalog = await system_catalog(db_session)
    img = {"models": {"primary": {"provider": "anthropic", "model": "claude-opus-4-20250514"}}}
    heads = resolve_default_heads(catalog, image_config=img, agent_overrides=None)
    assert heads["primary"]["model"] == "claude-opus-4-6"  # not the off-catalog id


async def test_head_must_match_kind(db_session):
    """A summarization-only model pinned as primary (reasoning) is rejected."""
    await seed_models(db_session)
    await db_session.commit()
    catalog = await system_catalog(db_session)
    # haiku is summarization-only in the seed.
    img = {"models": {"primary": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}}}
    heads = resolve_default_heads(catalog, image_config=img, agent_overrides=None)
    assert heads["primary"]["model"] == "claude-opus-4-6"  # fell back to reasoning default


async def test_admin_image_defaults_beat_catalog_default(db_session):
    """The admin-stored default model wins over the catalog recommended_default
    when neither the image nor the agent pins one — the Defaults-page-says-
    Sonnet-but-machines-spawn-Opus bug."""
    await seed_models(db_session)
    await db_session.commit()
    catalog = await system_catalog(db_session)
    stored = {"models": {"primary": {"provider": "anthropic",
                                     "model": "claude-sonnet-4-5-20250929"}}}
    heads = resolve_default_heads(
        catalog, image_config={"models": {"primary": {}, "fast": {}}},
        agent_overrides=None, image_defaults=stored,
    )
    assert heads["primary"]["model"] == "claude-sonnet-4-5-20250929"
    assert heads["fast"]["model"] == "claude-haiku-4-5-20251001"


async def test_image_and_agent_beat_admin_image_defaults(db_session):
    await seed_models(db_session)
    await db_session.commit()
    catalog = await system_catalog(db_session)
    stored = {"models": {"primary": {"provider": "anthropic",
                                     "model": "claude-sonnet-4-5-20250929"}}}
    img = {"models": {"primary": {"provider": "openai", "model": "gpt-4o"}}}
    heads = resolve_default_heads(
        catalog, image_config=img, agent_overrides=None, image_defaults=stored,
    )
    assert heads["primary"] == {"provider": "openai", "model": "gpt-4o"}

    ov = {"models": {"primary": {"provider": "anthropic", "model": "claude-opus-4-6"}}}
    heads = resolve_default_heads(
        catalog, image_config=img, agent_overrides=ov, image_defaults=stored,
    )
    assert heads["primary"]["model"] == "claude-opus-4-6"


# ── catalog_has (proxy wall) ─────────────────────────────────────────────────

async def test_catalog_has_id_alias_and_provider(db_session):
    await seed_models(db_session)
    await db_session.commit()
    catalog = await system_catalog(db_session)
    assert catalog_has(catalog, "anthropic", "claude-opus-4-6")
    assert catalog_has(catalog, "anthropic", "opus")          # alias resolves
    assert not catalog_has(catalog, "anthropic", "claude-3-opus-20240229")
    assert not catalog_has(catalog, "openai", "claude-opus-4-6")  # wrong provider
