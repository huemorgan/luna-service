"""One-time backfill for plan 016 — Composio two-accounts mode.

Walks every running Fly machine for the luna-agents app, resolves the
effective accounts_mode from the agent record + image config (per
cloud.provisioning.services_config), and pushes LUNA_CONNECTORS_ACCOUNTS_MODE
into the machine env via update_machine_env.

Idempotent: if the value is already correct, the in-place update is still
applied (Fly does a quick recreate; that's fine for our 8 machines).

Run locally with prod env. NOT imported by the app.

Usage:
    CLOUD_DATABASE_URL=... FLY_API_TOKEN=... python dev/backfill_016.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from sqlalchemy import select

    from cloud.api.admin_routes import DEFAULT_IMAGE_CONFIG
    from cloud.db.models import Agent, LunaImage
    from cloud.db.session import get_session
    from cloud.provisioning.services_config import (
        hosted_composio_key_provisioned,
        resolve_composio_accounts_mode,
    )
    from cloud.runtime.fly_machines import FlyMachinesRuntime

    fly = FlyMachinesRuntime()

    async with get_session() as db:
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
        hosted_provisioned = await hosted_composio_key_provisioned(db)

    print(f"Backfilling LUNA_CONNECTORS_ACCOUNTS_MODE for {len(agents)} agents")
    print(f"hosted_composio_key_provisioned={hosted_provisioned}")

    updated = 0
    errors = 0
    for agent in agents:
        image_cfg = image_cfg_by_version.get(agent.image_version or "")
        resolved = resolve_composio_accounts_mode(
            image_cfg, agent.config_overrides, hosted_key_provisioned=hosted_provisioned,
        )
        print(f"\n=== {agent.slug} ({agent.runtime_ref}) ===")
        print(f"  image={agent.image_version} override={agent.config_overrides} resolved={resolved}")
        try:
            await fly.update_machine_env(
                agent.runtime_ref, {"LUNA_CONNECTORS_ACCOUNTS_MODE": resolved},
            )
            print("  -> updated")
            updated += 1
        except Exception as e:
            print(f"  -> ERROR: {e}")
            errors += 1

    print(f"\nDone: updated={updated} errors={errors}")


if __name__ == "__main__":
    asyncio.run(main())
