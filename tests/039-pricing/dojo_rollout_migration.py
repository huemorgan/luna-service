"""039/010 dojo — enforcement overrides + account migration on real Postgres.

What SQLite unit tests cannot prove: alembic 0007 applies on real PG (columns
+ check constraint enforced by the server), the enforcement admin API against
a real app process, the operator-facing scripts/migrate_accounts.py run as a
real subprocess (exit codes are the operator contract), and the REAL worker
loop draining the migration's suspend jobs on its own cadence.

Self-contained: creates/migrates a scratch DB (dojo039rollout on the docker
PG at :5435), seeds an admin + three pre-cutover accounts with mixed Luna
states, boots real uvicorn (billing mode off — the production posture), and
drives everything over HTTP + subprocess.
Run: `python3 tests/039-pricing/dojo_rollout_migration.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from itsdangerous import URLSafeTimedSerializer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PG_ADMIN = "postgresql+asyncpg://luna:luna@localhost:5435/postgres"
DB_NAME = "dojo039rollout"
DB_URL = f"postgresql+asyncpg://luna:luna@localhost:5435/{DB_NAME}"
APP_PORT = 8105
BASE = f"http://127.0.0.1:{APP_PORT}"
API = f"{BASE}/api/admin/pricing"
SECRET = "dojo-session-secret"

RESULTS = Path(__file__).parent / "results" / f"{date.today().isoformat()}-local-010"
RESULTS.mkdir(parents=True, exist_ok=True)
report: list[str] = []


def ok(name: str) -> None:
    report.append(f"PASS  {name}")
    print(report[-1], flush=True)


async def _exec(url: str, *stmts: str, autocommit: bool = False):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(
        url, isolation_level="AUTOCOMMIT" if autocommit else "READ COMMITTED")
    out = []
    try:
        async with engine.connect() as conn:
            for stmt in stmts:
                out.append(await conn.execute(text(stmt)))
                if not autocommit:
                    await conn.commit()
        return out
    finally:
        await engine.dispose()


async def _rows(sql: str) -> list:
    res = await _exec(DB_URL, sql)
    return list(res[0].fetchall())


def run(coro):
    return asyncio.run(coro)


async def seed() -> dict:
    """Admin + three accounts in pre-migration shape:
    - mig-alpha: two running Lunas (one recently active) + one stopped
    - mig-beta:  one stopped Luna only
    - canary:    one running Luna — override tests + drift/tamper cohort
    Agents have no runtime_ref, so the real worker resolves suspend jobs as
    'skipped: no runtime' instead of calling Fly."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cloud.billing import ledger
    from cloud.billing.seed import seed_billing
    from cloud.db.models import Account, Agent, Membership, User

    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as db:
            await seed_billing(db)
            user = User(google_sub="dojo-rollout", email="dojo-rollout@example.com",
                        name="Dojo Rollout", is_admin=True)
            db.add(user)
            await db.flush()

            ids: dict = {"user_id": str(user.id)}

            def account(slug: str) -> Account:
                acc = Account(slug=slug, name=slug.title(), created_by=user.id)
                db.add(acc)
                return acc

            def agent(acc: Account, slug: str, status: str, active_ago_h: int | None):
                a = Agent(
                    account_id=acc.id, creator_id=user.id, name=slug, slug=slug,
                    status=status,
                    last_active_at=(now - timedelta(hours=active_ago_h))
                    if active_ago_h is not None else None,
                )
                db.add(a)
                return a

            alpha, beta, canary = account("mig-alpha"), account("mig-beta"), account("canary")
            await db.flush()
            db.add(Membership(account_id=alpha.id, user_id=user.id, role="owner"))
            for acc in (alpha, beta, canary):
                await ledger.ensure_billing_account(db, acc.id)

            keep = agent(alpha, "alpha-keep", "running", active_ago_h=1)
            stop = agent(alpha, "alpha-stop", "running", active_ago_h=720)
            agent(alpha, "alpha-idle", "stopped", active_ago_h=None)
            agent(beta, "beta-idle", "stopped", active_ago_h=None)
            canary_agent = agent(canary, "canary-run", "running", active_ago_h=2)
            await db.commit()

            ids.update(
                alpha=str(alpha.id), beta=str(beta.id), canary=str(canary.id),
                keep=str(keep.id), stop=str(stop.id), canary_agent=str(canary_agent.id),
            )
            return ids
    finally:
        await engine.dispose()


def mint_cookie(user_id: str, account_id: str) -> str:
    payload = json.dumps({"user_id": user_id, "account_id": account_id})
    return URLSafeTimedSerializer(SECRET).dumps(payload)


def boot_app() -> subprocess.Popen:
    env = {**os.environ,
           "CLOUD_DATABASE_URL": DB_URL,
           "CLOUD_SESSION_SECRET": SECRET,
           "CLOUD_BILLING_MODE": "off",   # production posture — overrides escalate
           "CLOUD_RELAY_FORWARDER": "0",
           "CLOUD_RECONCILER": "0",
           "CLOUD_BILLING_WORKER": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "cloud.main:app", "--port", str(APP_PORT),
         "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=(RESULTS / "app-rollout.log").open("w"), stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/healthz", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.3)
    proc.send_signal(signal.SIGTERM)
    raise RuntimeError("app did not become healthy")


def migrate_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/migrate_accounts.py", *args,
         "--database-url", DB_URL],
        cwd=str(ROOT), env={**os.environ}, capture_output=True, text=True,
    )


def main() -> None:
    run(_exec(PG_ADMIN, f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)',
              f'CREATE DATABASE {DB_NAME}', autocommit=True))
    subprocess.run([sys.executable, "-m", "cloud.db.migrate"], cwd=str(ROOT),
                   env={**os.environ, "CLOUD_DATABASE_URL": DB_URL}, check=True,
                   capture_output=True)
    (head,) = run(_rows("SELECT version_num FROM alembic_version"))[0]
    assert head == "0007", head
    ids = run(seed())
    ok("0 scratch DB migrated to alembic head 0007 (override columns), seeded")

    cutover = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    proc = boot_app()
    try:
        client = httpx.Client(
            cookies={"luna_session": mint_cookie(ids["user_id"], ids["alpha"])},
            timeout=15,
        )

        # 1 — enforcement state starts clean; global mode off
        state = client.get(f"{API}/enforcement").json()
        assert state["global_mode"] == "off" and state["overrides"] == []
        ok("1 GET /enforcement: global off, no overrides")

        # 2 — set an override on the canary; effective mode escalates
        resp = client.post(f"{API}/enforcement/overrides", json={
            "account_ids": [ids["canary"]], "mode": "enforce",
            "reason": "dojo canary — rollout step 7 rehearsal",
        })
        assert resp.status_code == 200, resp.text
        state = client.get(f"{API}/enforcement").json()
        ov = state["overrides"][0]
        assert ov["account_id"] == ids["canary"]
        assert ov["mode"] == "enforce" and ov["effective_mode"] == "enforce"
        hits = client.get(f"{API}/accounts/search", params={"q": "canary"}).json()
        assert hits["accounts"][0]["override"] == "enforce"
        (audit_count,) = run(_rows(
            "SELECT count(*) FROM audit_log WHERE action = 'pricing.enforcement.override'"))[0]
        assert audit_count == 1, audit_count
        ok("2 override enforce on canary: listed, effective=enforce, searchable, audited")

        # 3 — clear it; reason still required
        resp = client.post(f"{API}/enforcement/overrides", json={
            "account_ids": [ids["canary"]], "mode": None, "reason": ""})
        assert resp.status_code == 400  # no reason, no change
        resp = client.post(f"{API}/enforcement/overrides", json={
            "account_ids": [ids["canary"]], "mode": None, "reason": "dojo cleanup"})
        assert resp.status_code == 200
        assert client.get(f"{API}/enforcement").json()["overrides"] == []
        ok("3 clearing an override requires a reason; list is empty after")

        # 4 — the PG check constraint rejects junk override values server-side
        try:
            run(_exec(DB_URL,
                      "UPDATE billing_accounts SET enforcement_override = 'wat'"))
            raise AssertionError("check constraint did not fire")
        except Exception as exc:
            assert "ck_billing_account_override" in str(exc), exc
        ok("4 ck_billing_account_override rejects junk values on real PG")

        # 5 — dry run for the alpha+beta cohort via the operator script
        manifest_path = RESULTS / "manifest-cohort-1.json"
        res = migrate_script("plan", "--cutover-at", cutover,
                             "--account-ids", f"{ids['alpha']},{ids['beta']}",
                             "--out", str(manifest_path))
        assert res.returncode == 0, res.stderr
        manifest = json.loads(manifest_path.read_text())
        t = manifest["totals"]
        assert t["accounts"] == 2 and t["pending"] == 2
        assert t["keeps"] == 1 and t["stops"] == 1
        assert t["gift_credits_total"] == 3600 and t["hosting_charges_total"] == 999
        by_slug = {e["slug"]: e for e in manifest["per_account"]}
        assert by_slug["mig-alpha"]["keep_agent_id"] == ids["keep"]
        assert by_slug["mig-alpha"]["stop_agent_ids"] == [ids["stop"]]
        ok("5 plan: signed manifest — keep newest-active, stop 1, gifts 3600, hosting 999")

        # 6 — execute the manifest; money and jobs land exactly once
        res = migrate_script("execute", "--manifest", str(manifest_path),
                             "--actor", "dojo", "--out", str(RESULTS / "execute-1.json"))
        assert res.returncode == 0, res.stderr
        assert "MIGRATION EXECUTED" in res.stdout
        (grants,) = run(_rows("SELECT count(*) FROM credit_grants WHERE source_key LIKE 'migration:%'"))[0]
        assert grants == 2
        rows = run(_rows(
            "SELECT agent_id::text, state, price_credits FROM agent_hosting_periods"))
        assert rows == [(ids["keep"], "active", 999)], rows
        (alpha_bal,) = run(_rows(
            "SELECT coalesce(sum(credits), 0) FROM credit_ledger_postings "
            f"WHERE ledger_account = 'customer_wallet' AND account_id = '{ids['alpha']}'"))[0]
        (beta_bal,) = run(_rows(
            "SELECT coalesce(sum(credits), 0) FROM credit_ledger_postings "
            f"WHERE ledger_account = 'customer_wallet' AND account_id = '{ids['beta']}'"))[0]
        assert (alpha_bal, beta_bal) == (801, 1800), (alpha_bal, beta_bal)
        ok("6 execute: 2 gifts posted, keep charged 999 (801/1800 balances), period active")

        # 7 — the REAL worker loop drains the suspend job (no runtime → skipped)
        deadline = time.time() + 30
        while time.time() < deadline:
            rows = run(_rows(
                "SELECT status, result FROM billing_outbox "
                "WHERE job_type = 'hosting_suspend'"))
            if rows and rows[0][0] == "succeeded":
                break
            time.sleep(1)
        assert rows and rows[0][0] == "succeeded", rows
        assert rows[0][1] == {"skipped": "no runtime"}, rows
        ok("7 real worker drained the stop job: succeeded, 'skipped: no runtime'")

        # 8 — rerun the same manifest: pure replay, nothing new posted
        res = migrate_script("execute", "--manifest", str(manifest_path),
                             "--actor", "dojo", "--out", str(RESULTS / "execute-2.json"))
        assert res.returncode == 0, res.stderr
        result2 = json.loads((RESULTS / "execute-2.json").read_text())
        assert result2["totals"] == {"applied": 0, "replayed": 2,
                                     "gift_credits_posted": 0,
                                     "hosting_charges_posted": 0,
                                     "stop_jobs_enqueued": 0}
        (grants,) = run(_rows("SELECT count(*) FROM credit_grants WHERE source_key LIKE 'migration:%'"))[0]
        (periods,) = run(_rows("SELECT count(*) FROM agent_hosting_periods"))[0]
        assert (grants, periods) == (2, 1)
        ok("8 rerun: replayed 2, zero new grants/periods/charges/jobs")

        # 9 — tampered manifest aborts with exit 2 and zero writes
        canary_manifest = RESULTS / "manifest-canary.json"
        res = migrate_script("plan", "--cutover-at", cutover,
                             "--account-ids", ids["canary"],
                             "--out", str(canary_manifest))
        assert res.returncode == 0, res.stderr
        doc = json.loads(canary_manifest.read_text())
        doc["totals"]["gift_credits_total"] = 1  # post-review edit
        canary_manifest.write_text(json.dumps(doc))
        res = migrate_script("execute", "--manifest", str(canary_manifest),
                             "--actor", "dojo")
        assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
        assert "MIGRATION ABORTED" in res.stderr
        ok("9 tampered manifest: exit 2, MIGRATION ABORTED")

        # 10 — live-state drift aborts with exit 2 and zero writes
        res = migrate_script("plan", "--cutover-at", cutover,
                             "--account-ids", ids["canary"],
                             "--out", str(canary_manifest))
        assert res.returncode == 0, res.stderr
        run(_exec(DB_URL,
                  f"UPDATE agents SET status = 'stopped' WHERE id = '{ids['canary_agent']}'"))
        res = migrate_script("execute", "--manifest", str(canary_manifest),
                             "--actor", "dojo")
        assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
        assert "MIGRATION ABORTED" in res.stderr
        (canary_grants,) = run(_rows(
            "SELECT count(*) FROM credit_grants "
            f"WHERE account_id = '{ids['canary']}'"))[0]
        assert canary_grants == 0
        ok("10 drifted live state: exit 2, no writes for the canary account")

        # 11 — ledger invariants hold after the whole exercise
        inv = client.get(f"{API}/ops/invariants").json()
        assert inv["trial_balance"]["ok"], inv
        assert inv["projection_drift"]["ok"], inv
        assert inv["grant_remainders"]["ok"], inv
        ok("11 invariants (trial balance / projection / remainders) hold post-migration")

    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    (RESULTS / "dojo-rollout-report.txt").write_text("\n".join(report) + "\n")
    print(f"\n{len(report)} scenarios passed; results in {RESULTS}", flush=True)


if __name__ == "__main__":
    main()
