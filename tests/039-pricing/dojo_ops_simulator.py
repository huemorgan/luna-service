"""039/009 dojo — ops observability + pricing simulator against real Postgres.

What SQLite unit tests cannot prove: Postgres returns Decimal for SUM/COUNT
aggregates (a Decimal in a JSON response 500s — phase 008's lesson), JSONB
round-trips, and the REAL background loops (outbox worker, maintenance,
stale-hold reaper, ops alert evaluation) stamping heartbeats and executing
the pricing_sim job on their own 5s cadence — no test-harness run_once.

Self-contained: creates/migrates a scratch DB (dojo039ops on the docker PG at
:5435), seeds an admin + funded account + billable events + a dead stripe.*
job, boots real uvicorn, drives everything over HTTP with a minted session
cookie. Run: `python3 tests/039-pricing/dojo_ops_simulator.py`.
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
DB_NAME = "dojo039ops"
DB_URL = f"postgresql+asyncpg://luna:luna@localhost:5435/{DB_NAME}"
APP_PORT = 8104
BASE = f"http://127.0.0.1:{APP_PORT}"
API = f"{BASE}/api/admin/pricing"
SECRET = "dojo-session-secret"

RESULTS = Path(__file__).parent / "results" / f"{date.today().isoformat()}-local"
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


async def seed() -> dict:
    """Admin user, funded account, three billable gpt-4o events, and one
    dead stripe.* outbox job (the canonical critical alert signal)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cloud.billing import ledger, worker
    from cloud.billing.models import BillableEvent
    from cloud.billing.seed import seed_billing
    from cloud.db.models import Account, Membership, User
    from cloud.gateway.model_registry import seed_models
    from cloud.gateway.registry import seed_services

    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as db:
            await seed_services(db)
            await seed_models(db)
            await seed_billing(db)

            user = User(google_sub="dojo-ops", email="dojo-ops@example.com",
                        name="Dojo Ops", is_admin=True)
            db.add(user)
            await db.flush()
            acc = Account(slug="dojo-ops", name="Dojo Ops", created_by=user.id)
            db.add(acc)
            await db.flush()
            db.add(Membership(account_id=acc.id, user_id=user.id, role="owner"))
            await ledger.ensure_billing_account(db, acc.id)
            await ledger.create_grant(
                db, account_id=acc.id, source_type="gift", source_key="dojo-ops:gift",
                credits=100, visible_category="gift",
                effective_at=now - timedelta(days=2), expires_at=None, now=now,
            )
            for i in range(3):
                db.add(BillableEvent(
                    source_idempotency_key=f"dojo-op-{i}:1", call_id=f"dojo-op-{i}",
                    account_id=acc.id, service="llm", sku="llm_call", context="agent",
                    provider="openai", model="gpt-4o", attempt_number=1,
                    quantity_json={"input_tokens": 100}, vendor_cost_micro_usd=25_000,
                    cost_source="provider_usage", status="recorded",
                    event_at=now - timedelta(days=1, minutes=i),
                ))
            # Dead money job → dead_money_jobs alert must fire.
            job = await worker.enqueue(db, job_type="stripe.grant_for_invoice",
                                       payload={}, max_attempts=1)
            job.attempts = 1
            await worker.fail_job(db, job, error="dojo: poisoned", now=now)
            await db.commit()
            return {"user_id": str(user.id), "account_id": str(acc.id)}
    finally:
        await engine.dispose()


def mint_cookie(user_id: str, account_id: str) -> str:
    payload = json.dumps({"user_id": user_id, "account_id": account_id})
    return URLSafeTimedSerializer(SECRET).dumps(payload)


def boot_app() -> subprocess.Popen:
    env = {**os.environ,
           "CLOUD_DATABASE_URL": DB_URL,
           "CLOUD_SESSION_SECRET": SECRET,
           "CLOUD_BILLING_MODE": "off",
           "CLOUD_RELAY_FORWARDER": "0",
           "CLOUD_RECONCILER": "0",
           "CLOUD_BILLING_WORKER": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "cloud.main:app", "--port", str(APP_PORT),
         "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=(RESULTS / "app-ops.log").open("w"), stderr=subprocess.STDOUT,
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


def run(coro):
    return asyncio.run(coro)


def wait_for_state(client: httpx.Client, sim_id: str, want: str, timeout: float = 30) -> dict:
    """Poll until the REAL worker loop finishes the job — no test run_once."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"{API}/simulations/{sim_id}").json()
        if detail["state"] == want:
            return detail
        if detail["state"] == "failed":
            raise AssertionError(f"simulation failed: {detail.get('result')}")
        time.sleep(1)
    raise AssertionError(f"simulation never reached {want}")


def main() -> None:
    run(_exec(PG_ADMIN, f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)',
              f'CREATE DATABASE {DB_NAME}', autocommit=True))
    subprocess.run([sys.executable, "-m", "cloud.db.migrate"], cwd=str(ROOT),
                   env={**os.environ, "CLOUD_DATABASE_URL": DB_URL}, check=True,
                   capture_output=True)
    ids = run(seed())
    ok("0 scratch DB created, migrated to head, seeded")

    proc = boot_app()
    try:
        client = httpx.Client(
            cookies={"luna_session": mint_cookie(ids["user_id"], ids["account_id"])},
            timeout=15,
        )

        # 1 — ops snapshot on real Postgres (Decimal-cast proof: it JSONifies)
        resp = client.get(f"{API}/ops")
        assert resp.status_code == 200, resp.text
        snap = resp.json()
        for key in ("holds", "rated_charges", "would_block", "worker", "webhooks",
                    "hosting", "scheduled_lots", "clawback", "stripe_bindings",
                    "heartbeats"):
            assert key in snap, key
        assert snap["worker"]["dead_money_jobs"] == 1
        (RESULTS / "ops-snapshot.json").write_text(json.dumps(snap, indent=2))
        ok("1 GET /ops returns integer counters on Postgres; dead money job visible")

        # 2 — invariants replay clean over the seeded ledger
        inv = client.get(f"{API}/ops/invariants").json()
        assert inv["trial_balance"]["ok"], inv
        assert inv["projection_drift"]["ok"], inv
        assert inv["grant_remainders"]["ok"], inv
        ok("2 invariants (trial balance / projection / remainders) hold on PG")

        # 3 — create a half-cost simulation; the REAL worker loop executes it
        versions = client.get(f"{API}/versions").json()["versions"]
        v1 = versions[-1]["id"]
        resp = client.post(f"{API}/simulations", json={
            "baseline_version_id": v1, "candidate_version_id": v1,
            "transforms": {"cost_multiplier": "0.50"},
        })
        assert resp.status_code == 200, resp.text
        sim = resp.json()
        assert sim["state"] == "pending" and sim["event_count"] == 3
        detail = wait_for_state(client, sim["id"], "succeeded")
        r = detail["result"]
        # 3 calls × vendor 25_000, agent/mid margin 10_000 → ceil(35k/10k)=4 each.
        # Half cost: 12_500 + 10_000 → ceil(22.5k/10k)=3 each.
        assert r["baseline"]["credits"] == 12, r["baseline"]
        assert r["candidate"]["credits"] == 9, r["candidate"]
        assert r["delta"]["credits"] == -3
        (RESULTS / "simulation-result.json").write_text(json.dumps(r, indent=2))
        ok("3 half-cost simulation ran via the real 5s worker loop: 12 → 9 credits")

        # 4 — CSV export
        resp = client.get(f"{API}/simulations/{sim['id']}/csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert ids["account_id"] in resp.text
        ok("4 CSV export streams per-account rows")

        # 5 — rerun by manifest reproduces the identical result hash
        rerun = client.post(f"{API}/simulations/{sim['id']}/rerun", json={}).json()
        rerun_detail = wait_for_state(client, rerun["id"], "succeeded")
        assert rerun_detail["result"]["result_hash"] == r["result_hash"]
        ok("5 rerun by manifest → identical result_hash")

        # 6 — cancelled runs never publish, even though the job still executes
        resp = client.post(f"{API}/simulations", json={
            "baseline_version_id": v1, "candidate_version_id": v1,
        })
        sim2 = resp.json()
        resp = client.post(f"{API}/simulations/{sim2['id']}/cancel", json={})
        assert resp.json()["state"] == "cancelled"
        time.sleep(7)  # a full worker tick runs the queued job
        detail = client.get(f"{API}/simulations/{sim2['id']}").json()
        assert detail["state"] == "cancelled" and detail["result"] is None
        ok("6 cancel before run: job executes but never publishes a result")

        # 7 — alert evaluation: the dead stripe.* job fires critical
        active = client.post(f"{API}/ops/alerts/evaluate", json={}).json()["active"]
        assert any(a["alert_key"] == "dead_money_jobs" for a in active), active
        alerts = client.get(f"{API}/ops/alerts").json()["alerts"]
        row = next(a for a in alerts if a["alert_key"] == "dead_money_jobs")
        assert row["severity"] == "critical" and row["status"] == "active"
        ok("7 dead stripe.* job → dead_money_jobs critical alert active")

        # 8 — every background loop stamped its heartbeat on real PG
        snap = client.get(f"{API}/ops").json()
        names = {h["name"] for h in snap["heartbeats"]}
        for name in ("outbox_worker", "maintenance", "hold_reaper", "alert_eval"):
            assert name in names, f"missing heartbeat {name} (have {names})"
        ok("8 heartbeats: outbox_worker, maintenance, hold_reaper, alert_eval")

        # 9 — audit trail exists for create + rerun
        actions = [a[0] for a in run(_rows(
            "SELECT action FROM audit_log WHERE action LIKE 'pricing.simulation.%'"))]
        assert "pricing.simulation.create" in actions
        assert "pricing.simulation.rerun" in actions
        assert "pricing.simulation.cancel" in actions
        ok("9 audit log records simulation create/rerun/cancel")

        # 10 — production tables untouched by three simulation runs
        (txns,) = run(_rows("SELECT count(*) FROM credit_ledger_transactions"))[0]
        (charges,) = run(_rows("SELECT count(*) FROM rated_charges"))[0]
        assert charges == 0, "simulator must never write rated_charges"
        (RESULTS / "dojo-ops-report.txt").write_text("\n".join(report) + "\n")
        ok(f"10 simulator wrote no rated_charges (ledger txns from seed: {txns})")

    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    (RESULTS / "dojo-ops-report.txt").write_text("\n".join(report) + "\n")
    print(f"\n{len(report)} scenarios passed; results in {RESULTS}", flush=True)


if __name__ == "__main__":
    main()
