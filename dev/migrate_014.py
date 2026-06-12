"""One-time fleet migration for plan 014 — hard tenant isolation.

For each running Luna machine: provision an isolated per-agent database + role,
repoint LUNA_DATABASE_URL at it, rotate LUNA_TRUSTED_PROXY_SECRET to the
per-agent derived secret, and drop LUNA_DB_SCHEMA. The Fly machine is updated
in place (volume + id preserved) and restarts against its fresh DB.

Run locally with prod env. NOT imported by the app.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# slug -> agent UUID (from /api/admin/gateway/agents-light)
AGENTS = {
    "vaselin-test-0-08-002": "3edd60ed-391f-4c72-bde8-a8be5e765178",
    "vaselin-gateway-test-0-08-001": "531be6b9-69bf-45fb-bb7e-283757a554de",
    "vaselin-test-0-06-001": "fc71c592-13fd-4c29-8bc0-ea7c408a1a65",
    "vaselin-061": "f685c5b2-84c4-4b21-8348-8299c552dcc1",
    "guyre-lyanna": "1f008714-5aae-43b4-9eea-663ed4176d2d",
    "vaselin-test-0-04-001-2": "23f6bc58-b82b-4a06-bf17-ad0ff85100b0",
    "roy-moshe": "f0def852-1b77-4ad2-8d6c-95adaae95565",
    "alonna-my-luna": "dfed269e-4aba-4aec-9ce5-5a7acb24be0a",
}


async def main(only: str | None = None):
    from cloud.db.tenant_provisioner import provision_tenant_database
    from cloud.provisioning.workflow import _compose_agent_db_url
    from cloud.runtime.fly_machines import FlyMachinesRuntime
    from cloud.runtime.proxy_secret import derive_proxy_secret

    admin_url = os.environ["CLOUD_TENANT_DATABASE_URL"]
    root_secret = os.environ["CLOUD_TRUSTED_PROXY_SECRET"]
    fly = FlyMachinesRuntime()

    machines = await fly.list_machines()
    by_name = {m["name"]: m for m in machines}

    for slug, agent_id in AGENTS.items():
        if only and slug != only:
            continue
        name = f"luna-{slug}"
        m = by_name.get(name)
        if not m:
            print(f"SKIP {slug}: no machine")
            continue
        mid = m["id"]
        print(f"\n=== {slug} ({mid}) ===")

        td = await provision_tenant_database(admin_url, slug)
        db_url = _compose_agent_db_url(admin_url, td)
        secret = derive_proxy_secret(root_secret, agent_id)
        print(f"  db={td.db_name} url_db_ok={db_url.endswith('/' + td.db_name)} secret_len={len(secret)}")

        updates = {"LUNA_DATABASE_URL": db_url, "LUNA_TRUSTED_PROXY_SECRET": secret}

        # Mirror gateway vars into SDK-standard names (ANTHROPIC_BASE_URL, …)
        # so the pydantic-ai chat path routes through the gateway too.
        cur_env = m.get("config", {}).get("env", {})
        for k, v in cur_env.items():
            if k.startswith("LUNA_") and (k.endswith("_BASE_URL") or k.endswith("_API_KEY")):
                if "luna.com.ai/proxy/" in v or v.startswith("lsv1-"):
                    updates[k.removeprefix("LUNA_")] = v

        await fly.update_machine_env(
            mid,
            updates,
            remove_keys=["LUNA_DB_SCHEMA"],
        )
        print(f"  updated + healthy")

    await fly._client.aclose() if fly._client else None


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(only))
