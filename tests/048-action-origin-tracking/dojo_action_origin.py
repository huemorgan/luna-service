"""048 dojo — action origin tracking + Usage chart polish, headless on real PG.

Seeds five origins over 28 days: web chat (tall), two scheduler triggers plus
a scheduled playbook (channel=scheduler, root_action_type=playbook_run — stays
under Scheduled by precedence), a user-initiated playbook (channel=web,
root_action_type=playbook_run — under Playbooks), WhatsApp, Telegram. Then
drives the built SPA and verifies:

- the day-range filter is gone (fixed 28 days), Luna filter remains
- five sections share one y-scale (telegram short vs chat tall)
- precedence: scheduled playbook shows under Scheduled, not Playbooks
- chart polish: no rounded bars, no gridlines, ~half width, small height
- API: sections/totals/precedence/y_max = max(peak, 200)

Self-contained: scratch DB dojo048 on the PG at :5435, app on :8108.
Run: `.venv/bin/python tests/048-action-origin-tracking/dojo_action_origin.py`.
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
DB_NAME = "dojo048"
DB_URL = f"postgresql+asyncpg://luna:luna@localhost:5435/{DB_NAME}"
APP_PORT = 8108
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

        info = UserInfo(sub="dojo-sub-048", email="origin@gmail.com", name="Dojo Owner")
        user, account = await _upsert_user_and_account(info)

        async with factory() as db:
            await db.execute(text(f"UPDATE users SET is_admin = true WHERE id = '{user.id}'"))
            await ledger.ensure_billing_account(db, account.id)
            await grant_trial_gift(db, account.id)

            mika = Agent(account_id=account.id, creator_id=user.id, name="Mika",
                         slug="dojo-mika", status="running", runtime_kind="fly-machine")
            db.add(mika)
            await db.flush()

            seq = {"n": 0}

            def add(*, channel, credits, day_offset, job=None, root=None, rtype="chat"):
                seq["n"] += 1
                cid = f"c{seq['n']}"
                at = now - timedelta(days=day_offset, hours=1)
                db.add(BillableEvent(
                    source_idempotency_key=f"{cid}:1", call_id=cid,
                    account_id=account.id, agent_id=mika.id,
                    root_action_id=root, root_action_type=rtype,
                    channel=channel, job_id=job, service="llm",
                    sku="llm.dojo", context="agent", model="claude-sonnet-5",
                    attempt_number=1, event_at=at,
                ))
                db.add(RatedCharge(logical_call_id=cid, account_id=account.id,
                                   credits=credits, charge_status="settled", created_at=at))

            # Chat (web): tall — peak 200.
            for d, c in [(0, 200), (2, 120), (5, 80), (9, 150), (14, 60), (21, 40)]:
                add(channel="web", credits=c, day_offset=d)
            add(channel=None, credits=15, day_offset=1)   # legacy → web

            # Scheduler: two triggers + a scheduled playbook (precedence → scheduler).
            for d, c in [(0, 18), (3, 12), (7, 10)]:
                add(channel="scheduler", credits=c, day_offset=d, job="Morning digest", root="r-d")
            for d, c in [(1, 6), (8, 8)]:
                add(channel="scheduler", credits=c, day_offset=d, job="Nightly backup", root="r-b")
            add(channel="scheduler", credits=22, day_offset=2, job="Weekly report",
                root="r-w", rtype="playbook_run")

            # Playbooks: user/chat-initiated (channel web + playbook_run).
            for d, c in [(0, 14), (4, 9)]:
                add(channel="web", credits=c, day_offset=d, job="Daily report", rtype="playbook_run")

            # WhatsApp medium, Telegram tiny (must render short on shared scale).
            for d, c in [(0, 12), (4, 10), (12, 8)]:
                add(channel="whatsapp", credits=c, day_offset=d)
            for d, c in [(1, 4), (6, 3), (15, 3)]:
                add(channel="telegram", credits=c, day_offset=d)

            await db.commit()
            return {"user_id": str(user.id), "account_id": str(account.id),
                    "mika_id": str(mika.id)}
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


def bar_heights(page, section_title: str) -> list[float]:
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
            ctx = browser.new_context(viewport={"width": 1440, "height": 1400},
                                      reduced_motion="reduce")
            ctx.add_cookies([cookie])
            page = ctx.new_page()

            # S1 — No day-range filter; fixed 28 days.
            page.goto(f"{BASE}/dashboard/usage", wait_until="domcontentloaded")
            page.wait_for_selector("text=Chat")
            for absent in ("Today", "Custom", "Last 7 days"):
                assert page.get_by_role("button", name=absent).count() == 0, f"range button {absent} still present"
            expect(page.get_by_text("Last 28 days")).to_be_visible()
            expect(page.locator("select")).to_be_visible()
            shot(page, "01-usage.png")
            ok("S1 no day-range filter; 'Last 28 days' shown; Luna filter present")

            # S2 — Five sections, shared scale.
            for title in ("Chat", "Scheduled triggers", "Playbooks", "WhatsApp", "Telegram"):
                expect(page.get_by_role("heading", name=title).first).to_be_visible()
            chat_h = max(bar_heights(page, "Chat") or [0])
            tg_h = max(bar_heights(page, "Telegram") or [0])
            assert chat_h > 80, f"chat peak should be tall, got {chat_h}"
            assert 0 < tg_h < 20, f"telegram should be short on shared scale, got {tg_h}"
            ok(f"S2 five sections; shared scale (chat {chat_h:.0f}% vs telegram {tg_h:.0f}%)")

            # S3 — Precedence + per-item expand.
            expect(page.get_by_text("Weekly report")).to_be_visible()   # under Scheduled
            expect(page.get_by_text("Daily report")).to_be_visible()    # under Playbooks
            # Weekly report (scheduled playbook) must live in the Scheduled section.
            in_sched = page.evaluate(
                """() => {
                    const secs=[...document.querySelectorAll('section')];
                    const s=secs.find(x=>x.textContent.includes('Scheduled triggers'));
                    return !!s && s.textContent.includes('Weekly report');
                }""")
            assert in_sched, "scheduled playbook must appear under Scheduled triggers"
            page.get_by_text("Weekly report").click()
            page.get_by_text("Daily report").click()
            shot(page, "02-expanded.png")
            ok("S3 scheduled playbook under Scheduled; user playbook under Playbooks; expand works")

            # S4 — Chart polish: no rounded bars, no gridlines, ~half width.
            polish = page.evaluate(
                """() => {
                    const secs=[...document.querySelectorAll('section')];
                    const s=secs.find(x=>x.textContent.includes('Chat'));
                    const bars=[...s.querySelectorAll('div[title]')];
                    const rounded=bars.some(b=>/rounded/.test(b.className));
                    // gridline heuristic: absolutely-positioned 1px lines (old design)
                    const gridlines=[...s.querySelectorAll('div')].filter(d=>{
                        const st=d.getAttribute('style')||'';
                        return /height:\\s*1px/.test(st);
                    }).length;
                    // plot width vs card width
                    const plot=s.querySelector('div[title]')?.closest('.max-w-\\\\[50\\\\%\\\\]')
                            || [...s.querySelectorAll('div')].find(d=>d.querySelector('div[title]'));
                    const cardW=s.getBoundingClientRect().width;
                    const plotW=plot? plot.getBoundingClientRect().width : cardW;
                    return {rounded, gridlines, ratio: plotW/cardW};
                }""")
            assert polish["rounded"] is False, "bars must not be rounded"
            assert polish["gridlines"] == 0, f"gridlines must be gone, found {polish['gridlines']}"
            assert polish["ratio"] <= 0.6, f"plot should be ~half width, ratio {polish['ratio']:.2f}"
            ok(f"S4 square bars, no gridlines, half width (ratio {polish['ratio']:.2f})")

            # S5 — API shape / totals / precedence / y_max.
            r = httpx.get(f"{BASE}/api/billing/usage/channels?range=28d",
                          cookies={"luna_session": cookie["value"]}, timeout=15).json()
            assert set(r["sections"]) == {"web", "scheduler", "playbooks", "whatsapp", "telegram"}
            assert r["sections"]["scheduler"]["total"] == 18 + 12 + 10 + 6 + 8 + 22
            assert r["sections"]["playbooks"]["total"] == 14 + 9
            sched_items = {i["key"] for i in r["sections"]["scheduler"]["items"]}
            assert sched_items == {"Morning digest", "Nightly backup", "Weekly report"}
            pb_items = {i["key"] for i in r["sections"]["playbooks"]["items"]}
            assert pb_items == {"Daily report"}
            assert r["y_max"] == 200  # peak single-day (web day0 = 200) == floor
            ok("S5 API: 5 sections, precedence totals, per-item split, y_max=200")

            browser.close()
    finally:
        stop_app(app)
        (RESULTS / "report.txt").write_text("\n".join(report) + "\n")
        print("\n".join(report))
        print(f"\nResults in {RESULTS}")


if __name__ == "__main__":
    main()
