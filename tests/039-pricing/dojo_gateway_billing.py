"""039/004 dojo — live gateway billing against real Postgres.

No browser UI in this phase; the dojo is a real-network end-to-end run that
SQLite unit tests cannot give us: real uvicorn app + billing worker + stale-
hold reaper, real Postgres (savepoints, row locks, JSONB), a real HTTP mock
provider, and the actual 5s outbox settlement loop.

Self-contained: creates/migrates a scratch DB (dojo039gw on the docker PG at
:5435), seeds, boots the app once per billing mode, runs scenarios, asserts
directly against the DB. Run: `python3 tests/039-pricing/dojo_gateway_billing.py`.
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
import uuid
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PG_ADMIN = "postgresql+asyncpg://luna:luna@localhost:5435/postgres"
DB_NAME = "dojo039gw"
DB_URL = f"postgresql+asyncpg://luna:luna@localhost:5435/{DB_NAME}"
APP_PORT = 8103
UPSTREAM_PORT = 8109
BASE = f"http://127.0.0.1:{APP_PORT}"

RESULTS = Path(__file__).parent / "results" / f"{date.today().isoformat()}-local"
RESULTS.mkdir(parents=True, exist_ok=True)
report: list[str] = []


def ok(name: str) -> None:
    report.append(f"PASS  {name}")
    print(report[-1], flush=True)


# ── Mock provider upstream ───────────────────────────────────────────────────

UPSTREAM_CALLS: list[dict] = []


class _Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        UPSTREAM_CALLS.append({"path": self.path, "headers": dict(self.headers)})
        body = json.dumps({"data": []}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length)
        UPSTREAM_CALLS.append({"path": self.path, "headers": dict(self.headers),
                               "body": raw.decode(errors="replace")})
        try:
            req = json.loads(raw)
        except ValueError:
            req = {}
        if req.get("stream") is True:
            start = json.dumps({"type": "message_start", "message": {
                "id": "msg_sse", "model": "claude-opus-4-6",
                "usage": {"input_tokens": 1000, "output_tokens": 1}}})
            delta = json.dumps({"type": "message_delta", "usage": {"output_tokens": 500}})
            payload = (f"event: message_start\ndata: {start}\n\n"
                       f"event: message_delta\ndata: {delta}\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("request-id", "req_dojo_sse")
            self.end_headers()
            for i in range(0, len(payload), 40):  # force chunk splits on the wire
                self.wfile.write(payload[i:i + 40])
                self.wfile.flush()
                time.sleep(0.01)
        else:
            body = json.dumps({
                "id": "msg_dojo", "model": "claude-opus-4-6",
                "content": [{"type": "text", "text": "dojo-completion"}],
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            }).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("request-id", "req_dojo_json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


# ── DB helpers (in-process, direct engine) ───────────────────────────────────

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
    """Seed services/models/billing plus two accounts: funded and broke."""
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

            user = User(google_sub="dojo-sub", email="dojo@example.com", name="Dojo",
                        is_admin=True)
            db.add(user)
            await db.flush()
            out = {}
            for label, credits in (("funded", 100), ("broke", 0)):
                acc = Account(slug=f"dojo-{label}", name=f"Dojo {label}", created_by=user.id)
                db.add(acc)
                await db.flush()
                db.add(Membership(account_id=acc.id, user_id=user.id, role="owner"))
                agent = Agent(account_id=acc.id, creator_id=user.id, name=f"L-{label}",
                              slug=f"dojo-{label}-luna", status="running")
                db.add(agent)
                await db.flush()
                await ledger.ensure_billing_account(db, acc.id)
                if credits:
                    await ledger.create_grant(
                        db, account_id=acc.id, source_type="gift", source_key=f"dojo:{label}",
                        credits=credits, visible_category="gift",
                        effective_at=now - timedelta(days=1), expires_at=None, now=now,
                    )
                token = await issue_token(db, agent.id)
                out[label] = {"account_id": str(acc.id), "agent_id": str(agent.id),
                              "token": token}
            await db.commit()
            return out
    finally:
        await engine.dispose()


# ── App lifecycle ────────────────────────────────────────────────────────────

def boot_app(mode: str) -> subprocess.Popen:
    env = {**os.environ,
           "CLOUD_DATABASE_URL": DB_URL,
           "CLOUD_BILLING_MODE": mode,
           "CLOUD_RELAY_FORWARDER": "0",
           "CLOUD_RECONCILER": "0",
           "CLOUD_BILLING_WORKER": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "cloud.main:app", "--port", str(APP_PORT),
         "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=(RESULTS / f"app-{mode}.log").open("w"), stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/healthz", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.3)
    proc.send_signal(signal.SIGTERM)
    raise RuntimeError(f"app did not become healthy in mode={mode}")


def stop_app(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


MSG_BODY = json.dumps({"model": "claude-opus-4-6", "max_tokens": 100,
                       "messages": [{"role": "user", "content": "dojo-prompt"}]})


def call_messages(token: str, *, body: str = MSG_BODY, path: str = "v1/messages",
                  headers: dict | None = None) -> httpx.Response:
    return httpx.post(f"{BASE}/proxy/anthropic/{path}", content=body, timeout=30,
                      headers={"x-api-key": token, "content-type": "application/json",
                               **(headers or {})})


# ── Scenarios ────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


def main() -> None:
    os.environ["CLOUD_DATABASE_URL"] = DB_URL  # for in-process seeding imports

    # Fresh scratch DB + migrations
    run(_exec(PG_ADMIN, f'DROP DATABASE IF EXISTS {DB_NAME} (FORCE)',
              f'CREATE DATABASE {DB_NAME}', autocommit=True))
    subprocess.run([sys.executable, "-m", "cloud.db.migrate"], cwd=str(ROOT),
                   env={**os.environ, "CLOUD_DATABASE_URL": DB_URL}, check=True,
                   capture_output=True)
    ok("0 scratch DB created and migrated to head")

    upstream = ThreadingHTTPServer(("127.0.0.1", UPSTREAM_PORT), _Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    ids = run(seed())
    funded, broke = ids["funded"], ids["broke"]

    # ── observe ──────────────────────────────────────────────────────────
    app = boot_app("observe")
    try:
        r = call_messages(broke["token"])
        assert r.status_code == 200, r.text
        events = run(_rows("SELECT status, quantity_json FROM billable_events"))
        charges = run(_rows("SELECT charge_status, credits FROM rated_charges"))
        holds = run(_rows("SELECT id FROM billing_holds"))
        assert len(events) == 1 and len(charges) == 1 and holds == []
        assert charges[0][0] == "observed" and charges[0][1] == 4
        bal = run(_rows(f"SELECT posted_balance_credits FROM account_balance_projections "
                        f"WHERE account_id = '{broke['account_id']}'"))
        assert not bal or bal[0][0] == 0
        ok("1 observe: broke account passes; observed charge recorded; wallet untouched")
    finally:
        stop_app(app)

    # ── shadow ───────────────────────────────────────────────────────────
    app = boot_app("shadow")
    try:
        r = call_messages(broke["token"])
        assert r.status_code == 200, r.text
        row = run(_rows("SELECT charge_status, rule_snapshot->>'would_block' FROM rated_charges "
                        "ORDER BY created_at DESC LIMIT 1"))
        assert row[0][0] == "shadow" and row[0][1] == "credits_exhausted"
        assert run(_rows("SELECT id FROM billing_holds")) == []  # PG savepoint rolled back
        ok("2 shadow: real decision recorded (would_block=credits_exhausted), zero customer effect")
    finally:
        stop_app(app)

    # ── enforce ──────────────────────────────────────────────────────────
    app = boot_app("enforce")
    try:
        # broke account blocked before upstream
        before = len(UPSTREAM_CALLS)
        r = call_messages(broke["token"])
        assert r.status_code == 402 and r.json()["error"]["code"] == "credits_exhausted"
        assert len(UPSTREAM_CALLS) == before
        ok("3 enforce: empty wallet → 402 credits_exhausted, no provider contact")

        # funded happy path — real outbox worker settles within its 5s poll
        r = call_messages(funded["token"])
        assert r.status_code == 200, r.text
        deadline = time.time() + 20
        while time.time() < deadline:
            row = run(_rows(f"SELECT status FROM billing_holds WHERE account_id = "
                            f"'{funded['account_id']}' ORDER BY authorized_at DESC LIMIT 1"))
            if row and row[0][0] == "settled":
                break
            time.sleep(1)
        assert row and row[0][0] == "settled", f"hold state: {row}"
        bal = run(_rows(f"SELECT posted_balance_credits FROM account_balance_projections "
                        f"WHERE account_id = '{funded['account_id']}'"))
        assert bal[0][0] == 96, bal
        ok("4 enforce: JSON call held, worker settled 4 credits (100 → 96)")

        # streaming SSE parses usage from a chunk-split wire stream
        r = call_messages(funded["token"], body=json.dumps(
            {"model": "opus", "stream": True, "max_tokens": 100, "messages": []}))
        assert r.status_code == 200
        deadline = time.time() + 20
        while time.time() < deadline:
            ev = run(_rows("SELECT quantity_json, model FROM billable_events "
                           "WHERE provider_response_id = 'msg_sse'"))
            if ev:
                break
            time.sleep(1)
        assert ev, "SSE billable event missing"
        q = ev[0][0] if isinstance(ev[0][0], dict) else json.loads(ev[0][0])
        assert q == {"input_tokens": 1000, "output_tokens": 500}
        assert ev[0][1] == "claude-opus-4-6"  # alias 'opus' canonicalized
        ok("5 enforce: SSE stream usage parsed on the wire; alias canonicalized")

        # unknown route fails closed; free route always passes
        r = call_messages(funded["token"], path="v1/complete")
        assert r.status_code == 402 and r.json()["error"]["code"] == "sku_unpriced"
        r = httpx.get(f"{BASE}/proxy/anthropic/v1/models",
                      headers={"x-api-key": broke["token"]}, timeout=10)
        assert r.status_code == 200
        ok("6 enforce: unknown route → sku_unpriced; free route passes even broke")

        # X-Luna headers never reach the provider
        before = len(UPSTREAM_CALLS)
        r = call_messages(funded["token"], headers={"x-luna-call-id": "dojo-call",
                                                    "x-luna-root-action-type": "chat"})
        assert r.status_code == 200
        sent = UPSTREAM_CALLS[before]["headers"]
        assert not any(h.lower().startswith("x-luna-") for h in sent)
        ev = run(_rows(f"SELECT call_id, root_action_type FROM billable_events "
                       f"WHERE call_id = '{funded['agent_id']}:dojo-call'"))
        assert ev and ev[0][1] == "chat"
        ok("7 enforce: x-luna-* stripped upstream; correlation recorded namespaced")

        # every request ends in exactly one explainable state (worker polls 5s)
        deadline = time.time() + 30
        while time.time() < deadline:
            states = run(_rows("SELECT status, count(*) FROM billing_holds GROUP BY status"))
            if all(s == "settled" for s, _ in states):
                break
            time.sleep(2)
        assert all(s == "settled" for s, _ in states), states
        ok(f"8 all holds terminal: {dict(states)}")
    finally:
        stop_app(app)

    upstream.shutdown()
    (RESULTS / "REPORT-gateway.txt").write_text("\n".join(report) + "\n")
    print(f"\nAll {len(report)} scenarios passed. Evidence in {RESULTS}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        (RESULTS / "REPORT-gateway.txt").write_text("\n".join(report) + "\nFAILED — see traceback\n")
        raise
