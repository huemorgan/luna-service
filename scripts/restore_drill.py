"""Backup restore drill (plan 039/009).

Proves a database backup is actually restorable AND financially coherent:
restores a dump into a freshly created isolated database, checks the Alembic
revision matches this checkout's head, then replays the ledger invariants
(trial balance, projection drift, grant remainders) and captures the ops
snapshot. Exit code 0 only when the restore succeeded and every invariant
holds. Required before enforce mode (039/010 gate: "one completed restore
drill").

Never points at production for writes — the drill database is created,
restored into, verified, and dropped (unless --keep). The only production
touch is an optional read-only pg_dump when --source-url is used.

Usage (from repo root, inside cloud's venv):

  # Dump a source DB and drill on a local/isolated Postgres server:
  python scripts/restore_drill.py \
      --source-url  postgres://user:pw@host/dbname \
      --work-url    postgres://localhost:5432/postgres

  # Or drill from an existing pg_dump custom-format file (e.g. a downloaded
  # Render backup):
  python scripts/restore_drill.py \
      --dump-file   backups/prod-2026-07-15.dump \
      --work-url    postgres://localhost:5432/postgres

  --keep       keep the drill database for inspection (prints its URL)
  --json-out   also write the report JSON to a file

pg_dump/pg_restore must be on PATH and match the server's major version.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

CLOUD_DIR = REPO_ROOT / "cloud"


def _run(cmd: list[str]) -> None:
    print(f"  $ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{proc.stderr.strip()}")


def _plain_url(url: str) -> str:
    """psql-tool URL: strip any SQLAlchemy driver suffix."""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres://", "postgresql://"
    )


def _async_url(url: str) -> str:
    plain = _plain_url(url)
    return plain.replace("postgresql://", "postgresql+asyncpg://")


def _server_url(url: str, dbname: str) -> str:
    """Same server, different database name."""
    base, _, _ = _plain_url(url).rpartition("/")
    return f"{base}/{dbname}"


def _repo_head_revision() -> str:
    cfg = Config(str(CLOUD_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CLOUD_DIR / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


async def _psql(url: str, sql: str) -> None:
    engine = create_async_engine(_async_url(url), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


async def _verify(drill_url: str) -> dict:
    """Alembic revision check + ledger invariants + ops snapshot."""
    from cloud.billing import operations as ops

    engine = create_async_engine(_async_url(drill_url))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            db_rev = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
            head = _repo_head_revision()
            invariants = await ops.run_invariants(session)
            snapshot = await ops.ops_snapshot(session)
    finally:
        await engine.dispose()

    return {
        "alembic": {"database": db_rev, "repo_head": head, "ok": db_rev == head},
        "invariants": invariants,
        "snapshot": snapshot,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-url", help="database to pg_dump (read-only)")
    source.add_argument("--dump-file", help="existing pg_dump custom-format file")
    parser.add_argument("--work-url", required=True,
                        help="Postgres server for the isolated drill DB "
                             "(any maintenance DB on it, e.g. .../postgres)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the drill database after the run")
    parser.add_argument("--json-out", help="write the report JSON here too")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    drill_db = f"restore_drill_{started.strftime('%Y%m%d_%H%M%S')}"
    drill_url = _server_url(args.work_url, drill_db)

    with tempfile.TemporaryDirectory(prefix="restore-drill-") as tmp:
        dump_path = args.dump_file or f"{tmp}/source.dump"
        if args.source_url:
            print("1/4 dumping source database …", flush=True)
            _run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
                  f"--file={dump_path}", _plain_url(args.source_url)])
        else:
            print(f"1/4 using dump file {dump_path}", flush=True)
            if not Path(dump_path).is_file():
                print(f"dump file not found: {dump_path}", file=sys.stderr)
                return 2

        print(f"2/4 creating isolated database {drill_db} …", flush=True)
        await _psql(args.work_url, f'CREATE DATABASE "{drill_db}"')

        ok = False
        report: dict = {}
        try:
            print("3/4 restoring dump …", flush=True)
            _run(["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error",
                  f"--dbname={_plain_url(drill_url)}", dump_path])

            print("4/4 verifying — alembic revision + ledger invariants …", flush=True)
            verification = await _verify(drill_url)
            inv = verification["invariants"]
            ok = (
                verification["alembic"]["ok"]
                and inv["trial_balance"]["ok"]
                and inv["projection_drift"]["ok"]
                and inv["grant_remainders"]["ok"]
            )
            report = {
                "drill": "restore",
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "dump": "pg_dump --format=custom" if args.source_url else args.dump_file,
                "drill_database": drill_db,
                "ok": ok,
                **verification,
            }
        finally:
            if args.keep:
                print(f"keeping drill database: {_plain_url(drill_url)}", flush=True)
            else:
                await _psql(args.work_url, f'DROP DATABASE IF EXISTS "{drill_db}"')

    # The snapshot is large; print a summary and write the full report if asked.
    summary = {k: v for k, v in report.items() if k != "snapshot"}
    print(json.dumps(summary, indent=2, default=str))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str))
        print(f"full report written to {args.json_out}", flush=True)

    print(f"\nRESTORE DRILL {'PASSED' if ok else 'FAILED'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
