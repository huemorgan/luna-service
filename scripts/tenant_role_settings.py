"""Plan 073: apply the tenant-role guardrails (connection limit + timeouts +
TCP keepalives) to every existing ``luna_a_%`` role. Idempotent.

    CLOUD_TENANT_DATABASE_URL=postgresql+asyncpg://... python scripts/tenant_role_settings.py [--dry-run]
"""
from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cloud.db.tenant_provisioner import role_settings_sql  # noqa: E402


async def main() -> None:
    dry = "--dry-run" in sys.argv
    url = os.environ["CLOUD_TENANT_DATABASE_URL"]
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            roles = [r[0] for r in (await conn.execute(text(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'luna_a_%' ORDER BY 1"
            ))).all()]
            for role in roles:
                for stmt in role_settings_sql(role):
                    if dry:
                        print(stmt)
                    else:
                        await conn.execute(text(stmt))
            print(f"{'would apply' if dry else 'applied'} to {len(roles)} roles")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
