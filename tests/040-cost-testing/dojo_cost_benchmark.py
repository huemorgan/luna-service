"""040 dojo — cost benchmark end-to-end on real Postgres.

What SQLite unit tests cannot prove: the real durable worker picks up the
benchmark job, the HttpAgentDriver speaks real HTTP to an agent (mocked Luna
that calls back through the REAL gateway proxy + enforcement pipeline in
enforce mode), rated charges land synchronously, the collector attributes
them to steps, and the wallet actually drains by the run's total.

Topology (all localhost):
    benchmark job ──HTTP──▶ mock Luna agent (:8107)
                                 │  x-api-key = real gateway token
                                 ▼
    cloud app + gateway + billing worker (:8106, mode=enforce)
                                 │  proxied upstream
                                 ▼
                       mock Anthropic (:8108, fixed usage)

Self-contained: scratch DB dojo040bench on the docker PG at :5435.
Run: `python3 tests/040-cost-testing/dojo_cost_benchmark.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from itsdangerous import URLSafeTimedSerializer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PG_ADMIN = "postgresql+asyncpg://luna:luna@localhost:5435/postgres"
DB_NAME = "dojo040bench"
DB_URL = f"postgresql+asyncpg://luna:luna@localhost:5435/{DB_NAME}"
APP_PORT = 8106
AGENT_PORT = 8107
UPSTREAM_PORT = 8108
BASE = f"http://127.0.0.1:{APP_PORT}"
API = f"{BASE}/api/admin/pricing"
SECRET = "dojo-session-secret"

RESULTS = Path(__file__).parent / "results" / f"{date.today().isoformat()}-local"
RESULTS.mkdir(parents=True, exist_ok=True)
report: list[str] = []


def ok(name: str) -> None:
    report.append(f"PASS  {name}")
    print(report[-1], flush=True)


# ── Mock Anthropic upstream ──────────────────────────────────────────────────

class _Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        body = json.dumps({
            "id": "msg_dojo", "model": "claude-opus-4-6",
            "content": [{"type": "text", "text": "dojo-completion"}],
            "usage": {"input_tokens": 1000, "output_tokens": 500,
                      "cache_read_input_tokens": 200},
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("request-id", "req_dojo")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Mock Luna agent: the benchmark target ────────────────────────────────────
# Speaks the plugin_api surface the driver uses; every user message triggers
# one real gateway LLM call so billing flows through the actual pipeline.

AGENT_STATE: dict = {"gateway_token": None, "headers": []}


class _LunaAgent(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/conversations":
            self._json([{"id": "conv-dojo"}])
        elif self.path.endswith("/messages"):
            self._json([])
        else:
            self._json({}, 404)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        AGENT_STATE["headers"].append({"path": self.path, **dict(self.headers)})
        if self.path == "/api/auth/proxy-login":
            self._json({"access_token": "dojo-agent-token"})
        elif self.path == "/api/conversations":
            self._json({"id": "conv-dojo"})
        elif self.path.endswith("/messages"):
            # Real LLM call through the cloud gateway — this is what gets billed.
            r = httpx.post(
                f"{BASE}/proxy/anthropic/v1/messages",
                headers={"x-api-key": AGENT_STATE["gateway_token"],
                         "content-type": "application/json"},
                json={"model": "claude-opus-4-6", "max_tokens": 100,
                      "messages": [{"role": "user", "content": "dojo"}]},
                timeout=30,
            )
            status = "ok" if r.status_code == 200 else f"upstream {r.status_code}"
            payload = (f"event: done\ndata: {json.dumps({'status': status})}\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self._json({}, 404)


# ── DB helpers ───────────────────────────────────────────────────────────────

async def _exec(url: str, *stmts: str, autocommit: bool = False):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT" if autocommit else "READ COMMITTED")
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
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cloud.billing import ledger
    from cloud.billing.seed import seed_billing
    from cloud.db.models import Account, Agent, GatewayKey, Membership, User
    from cloud.gateway.crypto import encrypt_key
    from cloud.gateway.model_registry import seed_models
    from cloud.gateway.registry import seed_services
    from cloud.gateway.tokens import issue_token

    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as db:
            await seed_services(db)
            await seed_models(db)
            await seed_billing(db)
            await db.execute(text(
                "UPDATE gateway_services SET upstream_url = :u, enabled = true WHERE slug = 'anthropic'"
            ), {"u": f"http://127.0.0.1:{UPSTREAM_PORT}"})
            db.add(GatewayKey(service_slug="anthropic", scope="global", priority=1,
                              api_key_enc=encrypt_key("DOJO-REAL-KEY"), label="dojo",
                              is_active=True))

            user = User(google_sub="dojo-bench", email="dojo-bench@example.com",
                        name="Dojo Bench", is_admin=True)
            db.add(user)
            await db.flush()
            acc = Account(slug="dojo-bench", name="Dojo Bench", created_by=user.id)
            db.add(acc)
            await db.flush()
            db.add(Membership(account_id=acc.id, user_id=user.id, role="owner"))
            agent = Agent(account_id=acc.id, creator_id=user.id, name="Bench target",
                          slug="dojo-bench-luna", status="running",
                          internal_url=f"http://127.0.0.1:{AGENT_PORT}")
            db.add(agent)
            await db.flush()
            await ledger.ensure_billing_account(db, acc.id)
            await ledger.create_grant(
                db, account_id=acc.id, source_type="gift", source_key="dojo-bench:gift",
                credits=500, visible_category="gift",
                effective_at=now - timedelta(days=1), expires_at=None, now=now,
            )
            token = await issue_token(db, agent.id)
            await db.commit()
            return {"user_id": str(user.id), "account_id": str(acc.id),
                    "agent_id": str(agent.id), "gateway_token": token}
    finally:
        await engine.dispose()


def mint_cookie(user_id: str, account_id: str) -> str:
    payload = json.dumps({"user_id": user_id, "account_id": account_id})
    return URLSafeTimedSerializer(SECRET).dumps(payload)


def boot_app() -> subprocess.Popen:
    env = {**os.environ,
           "CLOUD_DATABASE_URL": DB_URL,
           "CLOUD_SESSION_SECRET": SECRET,
           "CLOUD_BILLING_MODE": "enforce",
           "CLOUD_RELAY_FORWARDER": "0",
           "CLOUD_RECONCILER": "0",
           "CLOUD_BILLING_WORKER": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "cloud.main:app", "--port", str(APP_PORT),
         "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=(RESULTS / "app.log").open("w"), stderr=subprocess.STDOUT,
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


def wait_run(client: httpx.Client, run_id: str, want: set[str], timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"{API}/benchmark/runs/{run_id}").json()
        if detail["state"] in want:
            return detail
        if detail["state"] in ("failed", "succeeded", "aborted"):
            raise AssertionError(f"run reached {detail['state']}, wanted {want}: {detail.get('error')}")
        time.sleep(2)
    raise AssertionError(f"run never reached {want}")


def main() -> None:
    os.environ["CLOUD_DATABASE_URL"] = DB_URL

    run(_exec(PG_ADMIN, f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)',
              f'CREATE DATABASE {DB_NAME}', autocommit=True))
    subprocess.run([sys.executable, "-m", "cloud.db.migrate"], cwd=str(ROOT),
                   env={**os.environ, "CLOUD_DATABASE_URL": DB_URL}, check=True,
                   capture_output=True)
    tables = run(_rows(
        "SELECT tablename FROM pg_tables WHERE tablename LIKE 'benchmark%' ORDER BY 1"))
    assert [t[0] for t in tables] == [
        "benchmark_runs", "benchmark_step_events", "benchmark_steps"], tables
    ok("0 scratch DB migrated to head; 0008 benchmark tables exist")

    ids = run(seed())
    AGENT_STATE["gateway_token"] = ids["gateway_token"]

    upstream = ThreadingHTTPServer(("127.0.0.1", UPSTREAM_PORT), _Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    luna = ThreadingHTTPServer(("127.0.0.1", AGENT_PORT), _LunaAgent)
    threading.Thread(target=luna.serve_forever, daemon=True).start()

    proc = boot_app()
    try:
        client = httpx.Client(
            cookies={"luna_session": mint_cookie(ids["user_id"], ids["account_id"])},
            # No Origin/Referer (server-to-server) — passes the CSRF guard.
            timeout=30,
        )

        # 1 — playbook is served and the coverage contract holds on the wire
        pb = client.get(f"{API}/benchmark/playbook").json()
        assert pb["uncovered_plugins"] == [], pb["uncovered_plugins"]
        assert set(pb["presets"]) == {"light", "regular", "heavy"}
        ok("1 playbook endpoint: full plugin coverage, presets present")

        # 2 — target flagging: reason required, then flag sticks
        r = client.post(f"{API}/benchmark/targets/{ids['agent_id']}",
                        json={"target": True})
        assert r.status_code == 400, r.text
        r = client.post(f"{API}/benchmark/targets/{ids['agent_id']}",
                        json={"target": True, "reason": "dojo test agent"})
        assert r.status_code == 200, r.text
        targets = client.get(f"{API}/benchmark/targets").json()["targets"]
        assert [t["id"] for t in targets] == [ids["agent_id"]]
        ok("2 target flag: reason enforced, flag visible")

        # 3 — real run through the real worker, driver, gateway, enforcement
        r = client.post(f"{API}/benchmark/runs", json={
            "agent_id": ids["agent_id"],
            "item_keys": ["chat.hello", "api.direct"],
            "repetitions": 2,
            "reason": "dojo end-to-end",
        })
        assert r.status_code == 201, r.text
        run_id = r.json()["id"]
        detail = wait_run(client, run_id, {"succeeded"})
        ok("3 run executed by the durable worker end-to-end")

        # 4 — attribution: chat steps carry the mock usage and real credits
        steps = {(s["item_key"], s["repetition"]): s for s in detail["steps"]}
        for rep in (1, 2):
            s = steps[("chat.hello", rep)]
            assert s["status"] == "succeeded", s
            assert s["llm_requests"] == 1, s
            assert s["input_tokens"] == 1000 and s["output_tokens"] == 500, s
            assert s["cache_read_tokens"] == 200, s
            assert s["credits"] > 0, "enforce mode must rate real credits"
            assert s["vendor_cost_micro_usd"] > 0, s
            assert s["per_model"], s
        for rep in (1, 2):
            s = steps[("api.direct", rep)]
            assert s["status"] == "succeeded" and s["credits"] == 0, s
        assert ("__background__", 1) in steps
        totals = detail["totals"]
        assert totals["credits"] == sum(s["credits"] for s in detail["steps"])
        assert detail["medians"]["chat.hello"]["samples"] == 2
        ok(f"4 attribution: 2×chat.hello = {totals['credits']} credits, "
           f"tokens/model/vendor$ per step, background bucket present")

        # 5 — the trigger log survives with verbatim quantities
        events = client.get(f"{API}/benchmark/runs/{run_id}/events").json()["events"]
        chat_events = [e for e in events if e["model"] == "claude-opus-4-6"]
        assert len(chat_events) == 2, [e["model"] for e in events]
        for e in chat_events:
            assert e["quantities"]["input_tokens"] == 1000
            assert e["billable_event_id"], "must link back to the billable event"
        assert sum(e["credits"] for e in chat_events) == totals["credits"]
        export = client.get(f"{API}/benchmark/runs/{run_id}/export").json()
        assert any(st["events"] for st in export["steps"])
        ok("5 trigger log: verbatim quantities, linked events, export document")

        # 6 — the wallet actually drained (enforce is real money movement).
        # Settlement is a durable outbox job on a 5s loop, so poll for it.
        deadline = time.time() + 30
        remaining = 500
        while time.time() < deadline:
            bal = run(_rows(f"""
                SELECT COALESCE(SUM(remaining_credits), 0) FROM credit_grants
                WHERE account_id = '{ids["account_id"]}'"""))
            remaining = int(bal[0][0])
            if remaining == 500 - totals["credits"]:
                break
            time.sleep(2)
        assert remaining == 500 - totals["credits"], (remaining, totals["credits"])
        charges = run(_rows(
            "SELECT COUNT(*) FROM rated_charges WHERE credits > 0 AND charge_status = 'settled'"))
        assert charges[0][0] == 2
        ok(f"6 wallet drained 500 → {remaining}; rated charges settled for real")

        # 7 — driver identity: derived proxy secret + user email reached the agent
        from cloud.runtime.proxy_secret import derive_proxy_secret
        expected = derive_proxy_secret("dev-proxy-secret", ids["agent_id"])
        login = next(h for h in AGENT_STATE["headers"]
                     if h["path"] == "/api/auth/proxy-login")
        assert login["x-luna-proxy-secret"] == expected
        assert login["x-luna-user"] == "dojo-bench@example.com"
        msg = next(h for h in AGENT_STATE["headers"] if h["path"].endswith("/messages"))
        assert msg["authorization"] == "Bearer dojo-agent-token"
        ok("7 driver auth: derived proxy secret, creator email, bearer token")

        # 8 — projection prices a preset from the measured medians
        proj = client.post(f"{API}/benchmark/projection", json={
            "run_id": run_id, "preset": "regular", "hosting_credits": 999,
        }).json()
        unit = detail["medians"]["chat.hello"]["credits"]
        hello_row = next(p for p in proj["per_item"] if p["item_key"] == "chat.hello")
        assert hello_row["unit_credits"] == unit and hello_row["freq"] == 30
        assert proj["monthly_credits"] >= 999 + unit * 30
        assert "web.search_summarize" in proj["missing_items"]  # not measured here
        ok(f"8 projection: regular preset → {proj['monthly_credits']} credits/month")

        # 9 — abort stops a live run between steps
        r = client.post(f"{API}/benchmark/runs", json={
            "agent_id": ids["agent_id"], "item_keys": ["chat.hello"] * 1,
            "repetitions": 10, "reason": "dojo abort test",
        })
        run2 = r.json()["id"]
        time.sleep(6)  # let the worker lease it and start stepping
        client.post(f"{API}/benchmark/runs/{run2}/abort", json={})
        detail2 = wait_run(client, run2, {"aborted"}, timeout=60)
        assert len(detail2["steps"]) < 10
        ok(f"9 abort: run stopped after {len(detail2['steps'])} of 10 steps")

        # 10 — audit trail for the money-adjacent actions
        audits = run(_rows(
            "SELECT action FROM audit_log WHERE action LIKE 'pricing.benchmark%'"))
        actions = sorted({a[0] for a in audits})
        assert actions == ["pricing.benchmark.run.aborted",
                           "pricing.benchmark.run.started",
                           "pricing.benchmark.target"], actions
        ok("10 audit rows: target flag, run start, abort")

    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        upstream.shutdown()
        luna.shutdown()

    (RESULTS / "report.txt").write_text("\n".join(report) + "\n")
    print(f"\nAll {len(report)} scenarios passed. Report: {RESULTS / 'report.txt'}")


if __name__ == "__main__":
    main()
