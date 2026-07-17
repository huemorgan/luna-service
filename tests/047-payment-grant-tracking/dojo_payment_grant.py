"""047 dojo — payment→grant tracking, headless on real Postgres.

Seeds three billing outbox jobs — a money-in job that SUCCEEDED but granted
nothing (the silent financial anomaly 047 targets), a healthy money-in grant
(must NOT be flagged), and an unrelated dead job — then drives the admin SPA:

- /admin/pricing overview shows a "Payments granted nothing" alert stat +
  the attention banner
- /admin/pricing/ops shows the stat + a detail section with the skip reason
- GET /api/admin/pricing/billing-jobs returns full detail, attention set
  excludes the healthy grant, and ?status_filter=succeeded includes it

Self-contained: scratch DB dojo047 on the PG at :5435, app on :8107.
Run: `.venv/bin/python tests/047-payment-grant-tracking/dojo_payment_grant.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from itsdangerous import URLSafeTimedSerializer
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PG_ADMIN = "postgresql+asyncpg://luna:luna@localhost:5435/postgres"
DB_NAME = "dojo047"
DB_URL = f"postgresql+asyncpg://luna:luna@localhost:5435/{DB_NAME}"
APP_PORT = 8107
BASE = f"http://127.0.0.1:{APP_PORT}"
SESSION_SECRET = "dojo-secret"

RESULTS = Path(__file__).parent / "results" / f"{date.today().isoformat()}-local"
RESULTS.mkdir(parents=True, exist_ok=True)
report: list[str] = []


def ok(name: str) -> None:
    report.append(f"PASS  {name}")
    print(report[-1], flush=True)


def run(coro):
    import threading
    box: dict = {}

    def _target():
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=_target)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


async def _exec(url: str, *stmts: str, autocommit: bool = False):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(
        url, isolation_level="AUTOCOMMIT" if autocommit else "READ COMMITTED"
    )
    try:
        async with engine.connect() as conn:
            for stmt in stmts:
                await conn.execute(text(stmt))
                if not autocommit:
                    await conn.commit()
    finally:
        await engine.dispose()


async def seed() -> dict:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cloud.api.auth_routes import _upsert_user_and_account
    from cloud.auth.identity import UserInfo
    from cloud.billing import ledger
    from cloud.billing.models import BillingJob
    from cloud.billing.seed import seed_billing

    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as db:
            await seed_billing(db)
            await db.commit()

        info = UserInfo(sub="dojo-sub-047", email="grants@gmail.com", name="Dojo Admin")
        user, account = await _upsert_user_and_account(info)

        async with factory() as db:
            await db.execute(text(f"UPDATE users SET is_admin = true WHERE id = '{user.id}'"))
            await ledger.ensure_billing_account(db, account.id)

            # The anomaly: money-in job ran to success, granted nothing.
            db.add(BillingJob(
                job_type="stripe.invoice_paid", status="succeeded",
                dedupe_key="evt_paid_nothing",
                payload={"event_id": "evt_paid_nothing", "object_id": "in_ghost"},
                result={"granted": False, "skipped": "no matching subscription for invoice"},
                attempts=1, created_at=now, updated_at=now,
            ))
            # Healthy grant — must NOT be flagged.
            db.add(BillingJob(
                job_type="stripe.invoice_paid", status="succeeded",
                dedupe_key="evt_paid_ok",
                payload={"event_id": "evt_paid_ok", "object_id": "in_good"},
                result={"granted": True, "credits": 9900},
                attempts=1, created_at=now, updated_at=now,
            ))
            # Unrelated dead job (part of the attention set, different concern).
            db.add(BillingJob(
                job_type="stripe.subscription_updated", status="dead",
                dedupe_key="evt_dead",
                payload={"event_id": "evt_dead"},
                last_error="boom", attempts=8, created_at=now, updated_at=now,
            ))
            await db.commit()
            return {"user_id": str(user.id), "account_id": str(account.id)}
    finally:
        await engine.dispose()


def boot_app() -> subprocess.Popen:
    env = {**os.environ,
           "CLOUD_DATABASE_URL": DB_URL,
           "CLOUD_BILLING_MODE": "enforce",
           "CLOUD_SESSION_SECRET": SESSION_SECRET,
           "CLOUD_BASE_URL": BASE,
           "CLOUD_RUNTIME": "fly-machines",
           "FLY_API_TOKEN": "dojo-invalid-token",
           "CLOUD_RELAY_FORWARDER": "0",
           "CLOUD_RECONCILER": "0",
           "CLOUD_BILLING_WORKER": "0"}
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


def stop_app(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def session_cookie(user_id: str, account_id: str) -> str:
    payload = json.dumps({"user_id": user_id, "account_id": account_id})
    return URLSafeTimedSerializer(SESSION_SECRET).dumps(payload)


def shot(page, name: str) -> None:
    page.screenshot(path=str(RESULTS / name), full_page=True)


def main() -> None:
    os.environ["CLOUD_DATABASE_URL"] = DB_URL
    run(_exec(PG_ADMIN, f'DROP DATABASE IF EXISTS {DB_NAME} (FORCE)',
              f'CREATE DATABASE {DB_NAME}', autocommit=True))
    subprocess.run([sys.executable, "-m", "cloud.db.migrate"], cwd=str(ROOT),
                   env={**os.environ, "CLOUD_DATABASE_URL": DB_URL}, check=True,
                   capture_output=True)
    ids = run(seed())
    app = boot_app()
    cookie = {"name": "luna_session",
              "value": session_cookie(ids["user_id"], ids["account_id"]), "url": BASE}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 1200},
                                      reduced_motion="reduce")
            ctx.add_cookies([cookie])
            page = ctx.new_page()

            # S1 — Overview stat + attention banner.
            page.goto(f"{BASE}/admin/pricing", wait_until="domcontentloaded")
            page.wait_for_selector("text=Payments granted nothing")
            txt = page.locator("body").inner_text()
            assert "Payments granted nothing" in txt
            assert "needs operator attention" in txt.lower()
            shot(page, "01-overview.png")
            ok("S1 overview shows 'Payments granted nothing' alert + attention banner")

            # S2 — Ops page stat + detail section with reason.
            page.goto(f"{BASE}/admin/pricing/ops", wait_until="domcontentloaded")
            page.wait_for_selector("text=Payments that granted nothing")
            ops_txt = page.locator("body").inner_text()
            assert "no matching subscription for invoice" in ops_txt
            assert "stripe.invoice_paid" in ops_txt
            shot(page, "02-ops.png")
            ok("S2 ops page lists the granted-nothing payment with its reason")

            # S3 — Admin API detail + filtering.
            c = {"luna_session": cookie["value"]}
            attention = httpx.get(f"{BASE}/api/admin/pricing/billing-jobs",
                                  cookies=c, timeout=15).json()["jobs"]
            events = {j["payload"].get("event_id") for j in attention}
            assert "evt_paid_nothing" in events, events
            assert "evt_dead" in events, events
            assert "evt_paid_ok" not in events, "healthy grant must not be flagged"
            anomaly = next(j for j in attention if j["payload"].get("event_id") == "evt_paid_nothing")
            assert anomaly["result"]["granted"] is False
            assert "no matching subscription" in anomaly["result"]["skipped"]

            succeeded = httpx.get(f"{BASE}/api/admin/pricing/billing-jobs?status_filter=succeeded",
                                  cookies=c, timeout=15).json()["jobs"]
            ev2 = {j["payload"].get("event_id") for j in succeeded}
            assert {"evt_paid_nothing", "evt_paid_ok"} <= ev2, ev2

            overview = httpx.get(f"{BASE}/api/admin/pricing/overview", cookies=c, timeout=15).json()
            assert overview["payments_granted_nothing"] == 1, overview["payments_granted_nothing"]
            ok("S3 /billing-jobs detail + attention set + status filter; overview count = 1")

            browser.close()
    finally:
        stop_app(app)
        (RESULTS / "report.txt").write_text("\n".join(report) + "\n")
        print("\n".join(report))
        print(f"\nResults in {RESULTS}")


if __name__ == "__main__":
    main()
