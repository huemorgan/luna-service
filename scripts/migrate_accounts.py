"""Existing-account migration runner (plan 039/010, review M9).

Wraps cloud/billing/migration.py for operators. Two subcommands:

  # Dry run — writes the signed manifest, mutates nothing:
  python scripts/migrate_accounts.py plan \
      --database-url postgres://... \
      --cutover-at 2026-08-01T00:00:00+00:00 \
      [--account-ids id1,id2,...] \
      --out manifest.json

  # Execute — verifies live state still matches the manifest, then applies:
  python scripts/migrate_accounts.py execute \
      --database-url postgres://... \
      --manifest manifest.json \
      --actor "roy" \
      [--out result.json]

Guard rails (from the plan):
  - Owner sign-off (M9) and customer notice happen BEFORE execute — this
    script does not send notices.
  - Execution stops with zero writes if any account's live state diverged
    from the manifest (MigrationMismatch, exit 2) — re-plan and re-review.
  - Reruns are safe: migrated accounts replay their prior grant/period.
  - Cohorts: pass --account-ids to migrate a bounded cohort; the cutover
    boundary excludes accounts created at/after --cutover-at either way.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _async_url(url: str) -> str:
    url = url.replace("postgres://", "postgresql://")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan", help="dry run — write the signed manifest")
    plan_p.add_argument("--cutover-at", required=True,
                        help="ISO timestamp; accounts created at/after are excluded")
    plan_p.add_argument("--account-ids", help="comma-separated cohort (default: all pre-cutover)")
    plan_p.add_argument("--out", required=True, help="manifest JSON path")

    exec_p = sub.add_parser("execute", help="apply a previously reviewed manifest")
    exec_p.add_argument("--manifest", required=True)
    exec_p.add_argument("--actor", required=True, help="who signed off (audit trail)")
    exec_p.add_argument("--out", help="write the execution result JSON here")

    for p in (plan_p, exec_p):
        p.add_argument("--database-url", default=os.environ.get("CLOUD_DATABASE_URL"),
                       help="defaults to CLOUD_DATABASE_URL")

    args = parser.parse_args()
    if not args.database_url:
        print("--database-url or CLOUD_DATABASE_URL is required", file=sys.stderr)
        return 2

    import uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cloud.billing import migration

    engine = create_async_engine(_async_url(args.database_url))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            if args.command == "plan":
                cutover = datetime.fromisoformat(args.cutover_at)
                if cutover.tzinfo is None:
                    cutover = cutover.replace(tzinfo=timezone.utc)
                ids = (
                    [uuid.UUID(x) for x in args.account_ids.split(",") if x.strip()]
                    if args.account_ids else None
                )
                manifest = await migration.plan_migration(
                    session, cutover_at=cutover, account_ids=ids
                )
                Path(args.out).write_text(json.dumps(manifest, indent=2))
                print(json.dumps({"totals": manifest["totals"],
                                  "content_hash": manifest["content_hash"]}, indent=2))
                print(f"manifest written to {args.out}")
                return 0

            manifest = json.loads(Path(args.manifest).read_text())
            try:
                result = await migration.execute_migration(
                    session, manifest=manifest, actor=f"migration-script:{args.actor}"
                )
            except migration.MigrationMismatch as exc:
                print(json.dumps({"aborted": str(exc),
                                  "mismatches": exc.mismatches}, indent=2, default=str))
                print("\nMIGRATION ABORTED — no writes. Re-plan and re-review.",
                      file=sys.stderr)
                return 2
            if args.out:
                Path(args.out).write_text(json.dumps(result, indent=2))
            print(json.dumps({"totals": result["totals"],
                              "manifest_hash": result["manifest_hash"]}, indent=2))
            print("MIGRATION EXECUTED")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
