"""One-time backfill for plan 018 — model catalog injection.

Walks every running Fly machine, resolves the system catalog + catalog-validated
default heads (per cloud.provisioning.model_catalog), and pushes
LUNA_MODEL_CATALOG + LUNA_PRIMARY_MODEL + LUNA_FAST_MODEL into the machine env via
update_machine_env. Fixes the brick-id default (claude-sonnet-4-20250514) on every
existing machine and gives them the real catalog.

Idempotent: the in-place update is always applied (Fly does a quick recreate;
fine for our handful of machines).

Run locally with prod env. NOT imported by the app.

Usage:
    CLOUD_DATABASE_URL=... FLY_API_TOKEN=... python dev/backfill_018.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from sqlalchemy import select

    from cloud.api.admin_routes import DEFAULT_IMAGE_CONFIG
    from cloud.db.models import Agent, LunaImage
    from cloud.db.session import get_session
    from cloud.gateway.model_registry import seed_models
    from cloud.provisioning.model_catalog import resolve_default_heads, system_catalog
    from cloud.runtime.fly_machines import FlyMachinesRuntime

    fly = FlyMachinesRuntime()

    async with get_session() as db:
        # Make sure the catalog is seeded before we read it.
        await seed_models(db)
        await db.commit()

        agents = (await db.execute(
            select(Agent).where(Agent.runtime_ref.isnot(None))
        )).scalars().all()
        versions = {a.image_version for a in agents if a.image_version}
        images = (await db.execute(
            select(LunaImage).where(LunaImage.version.in_(versions))
        )).scalars().all() if versions else []
        image_cfg_by_version = {
            img.version: {**DEFAULT_IMAGE_CONFIG, **(img.image_config or {})}
            for img in images
        }
        catalog = await system_catalog(db)

    catalog_json = json.dumps(catalog)
    print(f"Backfilling model catalog for {len(agents)} agents")
    print(f"catalog has {len(catalog)} enabled models")

    updated = 0
    errors = 0
    for agent in agents:
        image_cfg = image_cfg_by_version.get(agent.image_version or "")
        heads = resolve_default_heads(catalog, image_cfg, agent.config_overrides)
        primary = f"{heads['primary']['provider']}:{heads['primary']['model']}"
        fast = f"{heads['fast']['provider']}:{heads['fast']['model']}"
        print(f"\n=== {agent.slug} ({agent.runtime_ref}) ===")
        print(f"  image={agent.image_version} primary={primary} fast={fast}")
        try:
            await fly.update_machine_env(agent.runtime_ref, {
                "LUNA_MODEL_CATALOG": catalog_json,
                "LUNA_PRIMARY_MODEL": primary,
                "LUNA_FAST_MODEL": fast,
            })
            print("  -> updated")
            updated += 1
        except Exception as e:
            print(f"  -> ERROR: {e}")
            errors += 1

    print(f"\nDone: updated={updated} errors={errors}")


if __name__ == "__main__":
    asyncio.run(main())
