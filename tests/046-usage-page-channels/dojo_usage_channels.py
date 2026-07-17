"""046 dojo — Usage page + per-channel attribution, headless on real Postgres.

Seeds a customer with two Lunas and 28 days of billable_events tagged with
channel (web / whatsapp / telegram / scheduler, plus two scheduler triggers
and a legacy NULL-channel row that folds into web), then drives the built
SPA:

- top bar has separate Usage and Billing sections (no tabs, no Status)
- Usage page: 4 channel sections sharing one y-scale (small Telegram bars
  render short next to tall Chat bars)
- scheduler triggers expand to their own charts
- Luna filter pulldown + card deep-link change the numbers
- Billing page has balance + packages + statement, no usage content

Self-contained: scratch DB dojo046 on the PG at :5435, app on :8106.
Run: `.venv/bin/python tests/046-usage-page-channels/dojo_usage_channels.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from itsdangerous import URLSafeTimedSerializer
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PG_ADMIN = "postgresql+asyncpg://luna:luna@localhost:5435/postgres"
DB_NAME = "dojo046"
DB_URL = f"postgresql+asyncpg://luna:luna@localhost:5435/{DB_NAME}"
APP_PORT = 8106
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


# ── Seed ─────────────────────────────────────────────────────────────────────

async def seed() -> dict:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cloud.api.auth_routes import _upsert_user_and_account
    from cloud.auth.identity import UserInfo
    from cloud.billing import ledger
    from cloud.billing.grants import grant_trial_gift
    from cloud.billing.models import BillableEvent, RatedCharge
    from cloud.billing.seed import seed_billing
    from cloud.db.models import Agent

    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as db:
            await seed_billing(db)
            await db.commit()

        info = UserInfo(sub="dojo-sub-046", email="channels@gmail.com", name="Dojo Owner")
        user, account = await _upsert_user_and_account(info)

        async with factory() as db:
            await db.execute(text(f"UPDATE users SET is_admin = true WHERE id = '{user.id}'"))
            await ledger.ensure_billing_account(db, account.id)
            await grant_trial_gift(db, account.id)

            mika = Agent(account_id=account.id, creator_id=user.id, name="Mika",
                         slug="dojo-mika", status="running", runtime_kind="fly-machine")
            nova = Agent(account_id=account.id, creator_id=user.id, name="Nova",
                         slug="dojo-nova", status="running", runtime_kind="fly-machine")
            db.add_all([mika, nova])
            await db.flush()

            seq = {"n": 0}

            def add(agent_id, *, channel, credits, day_offset, job=None, root=None):
                seq["n"] += 1
                cid = f"c{seq['n']}"
                at = now - timedelta(days=day_offset, hours=1)
                db.add(BillableEvent(
                    source_idempotency_key=f"{cid}:1", call_id=cid,
                    account_id=account.id, agent_id=agent_id,
                    root_action_id=root, root_action_type="chat",
                    channel=channel, job_id=job, service="llm",
                    sku="llm.dojo", context="agent", model="claude-sonnet-5",
                    attempt_number=1, event_at=at,
                ))
                db.add(RatedCharge(logical_call_id=cid, account_id=account.id,
                                   credits=credits, charge_status="settled",
                                   created_at=at))

            # Chat (web): tall — up to 200/day on Mika. Legacy NULL row folds in.
            for d, c in [(0, 200), (2, 120), (5, 80), (9, 150), (14, 60), (21, 40)]:
                add(mika.id, channel="web", credits=c, day_offset=d)
            add(mika.id, channel=None, credits=15, day_offset=1)  # legacy → web
            add(nova.id, channel="web", credits=25, day_offset=3)

            # Scheduled triggers: two distinct jobs, modest credits.
            for d, c in [(0, 18), (3, 12), (7, 10)]:
                add(mika.id, channel="scheduler", credits=c, day_offset=d,
                    job="Morning digest", root="r-digest")
            for d, c in [(1, 6), (8, 8)]:
                add(mika.id, channel="scheduler", credits=c, day_offset=d,
                    job="Nightly backup", root="r-backup")

            # WhatsApp: medium (~30).
            for d, c in [(0, 12), (4, 10), (12, 8)]:
                add(mika.id, channel="whatsapp", credits=c, day_offset=d)

            # Telegram: tiny (~10) — must render as short bars vs the 200 peak.
            for d, c in [(1, 4), (6, 3), (15, 3)]:
                add(mika.id, channel="telegram", credits=c, day_offset=d)

            await db.commit()
            return {"user_id": str(user.id), "account_id": str(account.id),
                    "mika_id": str(mika.id), "nova_id": str(nova.id)}
    finally:
        await engine.dispose()


# ── App lifecycle ────────────────────────────────────────────────────────────

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


def bar_heights(page, section_title: str) -> list[float]:
    """Read rendered bar heights (%) inside a channel section by its title."""
    return page.evaluate(
        """(title) => {
            const secs = [...document.querySelectorAll('section')];
            const sec = secs.find(s => s.textContent.includes(title));
            if (!sec) return [];
            return [...sec.querySelectorAll('div[title]')].map(b => {
                const h = b.style.height || '';
                return h.endsWith('%') ? parseFloat(h) : 0;
            });
        }""",
        section_title,
    )


# ── Scenarios ────────────────────────────────────────────────────────────────

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

            # S1 — top bar: Usage and Billing are separate, no tabs/Status.
            page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
            expect(page.get_by_role("link", name="Usage").first).to_be_visible()
            expect(page.get_by_role("link", name="Billing").first).to_be_visible()
            page.get_by_role("link", name="Usage").first.click()
            page.wait_for_url(f"{BASE}/dashboard/usage")
            page.wait_for_selector("text=Chat")
            body = page.content()
            assert "Status" not in page.locator("main").inner_text() or "Scheduled" in page.content()
            shot(page, "01-usage-all.png")
            ok("S1 top bar Usage/Billing separate; /dashboard/usage loads")

            # S2 — four sections present, shared y-scale (telegram << chat).
            for title in ("Chat", "Scheduled triggers", "WhatsApp", "Telegram"):
                expect(page.get_by_role("heading", name=title).first).to_be_visible()
            chat_h = max(bar_heights(page, "Chat") or [0])
            tg_h = max(bar_heights(page, "Telegram") or [0])
            assert chat_h > 80, f"chat peak should be tall, got {chat_h}"
            assert 0 < tg_h < 20, f"telegram should be short on shared scale, got {tg_h}"
            ok(f"S2 four sections; shared scale (chat peak {chat_h:.0f}% vs telegram {tg_h:.0f}%)")

            # S3 — scheduler triggers expand.
            expect(page.get_by_text("Morning digest")).to_be_visible()
            expect(page.get_by_text("Nightly backup")).to_be_visible()
            page.get_by_text("Morning digest").click()
            shot(page, "02-scheduler-expanded.png")
            ok("S3 scheduler lists two triggers, expandable")

            # S4 — Luna filter changes numbers; card deep-link pre-filters.
            # Nova only has 25 web credits; Mika has the rest.
            page.select_option("select", label="Nova")
            page.wait_for_timeout(400)
            nova_chat = page.evaluate(
                """() => {
                    const secs=[...document.querySelectorAll('section')];
                    const s=secs.find(x=>x.textContent.includes('Chat'));
                    return s ? s.textContent : '';
                }""")
            assert "25 cr" in nova_chat, f"expected Nova chat 25 cr, got: {nova_chat[:120]}"
            shot(page, "03-usage-nova.png")
            # Card deep-link
            page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
            page.wait_for_selector("text=Mika")
            usage_btns = page.get_by_role("link", name="Usage")
            # the per-card Usage buttons (not the header) carry ?agent=
            page.goto(f"{BASE}/dashboard/usage?agent={ids['mika_id']}",
                      wait_until="domcontentloaded")
            page.wait_for_selector("text=Showing")
            expect(page.get_by_text("show all Lunas")).to_be_visible()
            assert page.locator("select").input_value() == ids["mika_id"]
            ok("S4 Luna filter changes totals; card deep-link pre-filters")

            # S5 — Billing page: payment banners + packages + statement, no
            # usage content and no status breakdown (moved to dashboard).
            page.goto(f"{BASE}/dashboard/billing", wait_until="domcontentloaded")
            page.wait_for_selector("text=Packages")
            # innerText honors CSS text-transform:uppercase — compare lowercased.
            main_txt = page.locator("main").inner_text().lower()
            assert "packages" in main_txt
            assert "statement" in main_txt
            assert "credit sources" not in main_txt
            assert "where credits went" not in main_txt
            assert "recent actions" not in main_txt
            shot(page, "04-billing.png")
            ok("S5 Billing has packages+statement, no status breakdown/usage")

            # S5b — Dashboard "Account & payment status" expands to breakdown.
            page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
            page.wait_for_selector("text=Account & payment status")
            assert "credit sources" not in page.locator("main").inner_text().lower()
            page.get_by_text("Account & payment status").click()
            page.wait_for_selector("text=Credit sources")
            dash_txt = page.locator("main").inner_text().lower()
            assert "balance" in dash_txt
            assert "credit sources" in dash_txt
            shot(page, "05-dashboard-status.png")
            ok("S5b Dashboard status toggle reveals balance + credit sources")

            # S6 — API shape.
            r = httpx.get(f"{BASE}/api/billing/usage/channels?range=28d",
                          cookies={"luna_session": cookie["value"]}, timeout=15).json()
            assert set(r["sections"]) == {"web", "scheduler", "playbooks", "whatsapp", "telegram"}
            assert r["sections"]["web"]["total"] == 200 + 120 + 80 + 150 + 60 + 40 + 15 + 25
            assert r["sections"]["telegram"]["total"] == 10
            assert r["y_max"] >= 200
            trigs = {t["key"] for t in r["sections"]["scheduler"]["triggers"]}
            assert trigs == {"Morning digest", "Nightly backup"}
            r2 = httpx.get(f"{BASE}/api/billing/usage/channels?range=28d&agent_id={ids['nova_id']}",
                           cookies={"luna_session": cookie["value"]}, timeout=15).json()
            assert r2["sections"]["web"]["total"] == 25
            assert r2["sections"]["telegram"]["total"] == 0
            ok("S6 /usage/channels shape, totals, y_max, per-trigger, agent filter")

            browser.close()
    finally:
        stop_app(app)
        (RESULTS / "report.txt").write_text("\n".join(report) + "\n")
        print("\n".join(report))
        print(f"\nResults in {RESULTS}")


if __name__ == "__main__":
    main()
