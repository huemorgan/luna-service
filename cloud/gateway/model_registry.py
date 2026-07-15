"""Plan 018 — seed data for the system model catalog (gateway_models).

This is the authoritative list of models luna-service serves, injected into every
tenant as LUNA_MODEL_CATALOG (Luna 007.016 contract). Kept in lockstep with what
the proxy actually 200s on. Aligned with Luna's baked models_catalog.yaml minus
anything our proxy can't serve (Gemini: no base_url support).

Shape mirrors Luna's ModelCatalogEntry. `enabled` = in/out of the catalog.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import GatewayModel

SEED_MODELS: list[dict] = [
    # ---- Anthropic ----
    {
        "provider": "anthropic", "model": "claude-opus-4-6",
        "label": "Claude Opus 4.6", "context_window": 200000,
        "kinds": ["reasoning"], "aliases": ["opus", "opus-4.6", "claude-opus"],
        "recommended_default": True, "input_cost": 5.0, "output_cost": 25.0,
    },
    {
        "provider": "anthropic", "model": "claude-sonnet-4-5-20250929",
        "label": "Claude Sonnet 4.5", "context_window": 200000,
        "kinds": ["reasoning", "summarization"],
        "aliases": ["sonnet", "sonnet-4.5", "claude-sonnet"],
        "input_cost": 3.0, "output_cost": 15.0,
    },
    {
        "provider": "anthropic", "model": "claude-haiku-4-5-20251001",
        "label": "Claude Haiku 4.5", "context_window": 200000,
        "kinds": ["summarization"], "aliases": ["haiku", "claude-haiku"],
        "recommended_default": True, "input_cost": 1.0, "output_cost": 5.0,
    },
    {
        # Transition entry: machines provisioned before 018 may still be pinned to
        # this head until the backfill runs. Kept enabled+deprecated so the proxy
        # never 404s a live agent mid-rollout; never a default. Safe to remove
        # from the admin catalog once every machine is migrated.
        "provider": "anthropic", "model": "claude-sonnet-4-20250514",
        "label": "Claude Sonnet 4 (legacy)", "context_window": 200000,
        "kinds": ["reasoning", "summarization"], "aliases": [],
        "deprecated": True, "input_cost": 3.0, "output_cost": 15.0,
    },
    # ---- OpenAI ----
    {
        "provider": "openai", "model": "gpt-4o",
        "label": "GPT-4o", "context_window": 128000,
        "kinds": ["reasoning", "summarization"], "aliases": ["gpt4o", "4o"],
        "input_cost": 2.5, "output_cost": 10.0,
    },
    {
        "provider": "openai", "model": "gpt-4o-mini",
        "label": "GPT-4o mini", "context_window": 128000,
        "kinds": ["summarization"], "aliases": ["gpt4o-mini", "4o-mini"],
        "input_cost": 0.15, "output_cost": 0.6,
    },
    {
        "provider": "openai", "model": "text-embedding-3-small",
        "label": "Embedding 3 Small", "kinds": ["embedding"],
        "aliases": ["embed-small", "embedding-small"],
        "recommended_default": True, "input_cost": 0.02, "output_cost": 0.0,
    },
    {
        "provider": "openai", "model": "text-embedding-3-large",
        "label": "Embedding 3 Large", "kinds": ["embedding"],
        "aliases": ["embed-large", "embedding-large"],
        "input_cost": 0.13, "output_cost": 0.0,
    },
    # ---- xAI (Grok) ---- prices from GET /v1/language-models, 2026-07-15
    {
        "provider": "xai", "model": "grok-4.5",
        "label": "Grok 4.5", "context_window": 500000,
        "kinds": ["reasoning"], "aliases": ["grok", "grok-4.5-latest"],
        "input_cost": 2.0, "output_cost": 6.0,
    },
    {
        "provider": "xai", "model": "grok-4.3",
        "label": "Grok 4.3", "context_window": 1000000,
        "kinds": ["reasoning", "summarization"], "aliases": ["grok-4.3-latest"],
        "input_cost": 1.25, "output_cost": 2.5,
    },
    {
        "provider": "xai", "model": "grok-build-0.1",
        "label": "Grok Build 0.1", "context_window": 256000,
        "kinds": ["reasoning"], "aliases": ["grok-build", "grok-build-latest"],
        "input_cost": 1.0, "output_cost": 2.0,
    },
]


async def seed_models(db: AsyncSession) -> None:
    """Insert seed rows for any (provider, model) not already present. Never
    overwrites admin edits — additive only."""
    existing = set((await db.execute(
        select(GatewayModel.provider, GatewayModel.model)
    )).all())
    for spec in SEED_MODELS:
        if (spec["provider"], spec["model"]) in existing:
            continue
        db.add(GatewayModel(**spec))
    await db.flush()
