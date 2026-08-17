"""Plan 073/074: apply the tenant-role guardrails (connection limit, idle
timeouts, TCP keepalives) to every existing ``luna_a_%`` role. Idempotent.

    CLOUD_TENANT_DATABASE_URL=postgresql+asyncpg://user:pw@host/db \
        python scripts/tenant_role_settings.py [--dry-run]

Uses asyncpg directly (ssl=require) — the Render host in the CP env var is
the internal name; pass the external one when running from outside Render.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cloud.db.tenant_provisioner import role_settings_sql  # noqa: E402


async def main() -> None:
    dry = "--dry-run" in sys.argv
    url = re.sub(r"^postgresql\+asyncpg:", "postgresql:", os.environ["CLOUD_TENANT_DATABASE_URL"])
    conn = await asyncpg.connect(url, ssl="require")
    try:
        roles = [r["rolname"] for r in await conn.fetch(
            "SELECT rolname FROM pg_roles WHERE rolname LIKE 'luna_a_%' ORDER BY 1"
        )]
        for role in roles:
            for stmt in role_settings_sql(role):
                if dry:
                    print(stmt)
                else:
                    await conn.execute(stmt)
        print(f"{'would apply' if dry else 'applied'} to {len(roles)} roles")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
