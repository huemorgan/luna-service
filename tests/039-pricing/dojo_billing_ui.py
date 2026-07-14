"""039/008 dojo — customer billing UI headless against real Postgres.

Covers what SQLite API tests can't: the built SPA rendering the public
pricing page (packages from /api/public/pricing, no hardcoded tiers), the
/dashboard/billing page (balance, trial, packages with payments disabled,
grants, usage trend, per-Luna limits editing through the real same-origin
PUT, actions, statement running balance), and the AgentDetail Spend card.

Self-contained: scratch DB dojo039bill on the docker PG at :5435, app on
:8105 with the billing worker on. Signup goes through the real in-process
`_upsert_user_and_account` (the HTTP signup path is allowlist-gated).
Run: `python3 tests/039-pricing/dojo_billing_ui.py`.
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
DB_NAME = "dojo039bill"
DB_URL = f"postgresql+asyncpg://luna:luna@localhost:5435/{DB_NAME}"
APP_PORT = 8105
BASE = f"http://127.0.0.1:{APP_PORT}"
SESSION_SECRET = "dojo-secret"

RESULTS = Path(__file__).parent / "results" / f"{date.today().isoformat()}-local"
RESULTS.mkdir(parents=True, exist_ok=True)
report: list[str] = []


def ok(name: str) -> None:
    report.append(f"PASS  {name}")
    print(report[-1], flush=True)


def run(coro):
    # Own thread + fresh loop: sync_playwright keeps an asyncio loop running
    # on the main thread, where asyncio.run() would raise.
    import threading
    box: dict = {}

    def _target():
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as e:  # re-raised below on the caller's thread
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


async def _rows(sql: str) -> list:
    res = await _exec(DB_URL, sql)
    return list(res[0].fetchall())


# ── Seed ─────────────────────────────────────────────────────────────────────

async def seed() -> dict:
    """Real signup + one Luna with a week of varied usage."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cloud.api.auth_routes import _upsert_user_and_account
    from cloud.auth.identity import UserInfo
    from cloud.billing import ledger
    from cloud.billing.models import (
        AgentCreditLimit, AgentHostingPeriod, AgentLimitPeriod, BillableEvent, RatedCharge,
    )
    from cloud.billing.rating import resolve_commercial_version
    from cloud.billing.seed import seed_billing
    from cloud.db.models import Agent

    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as db:
            await seed_billing(db)
            await db.commit()

        info = UserInfo(sub="dojo-sub-8", email="vaselin@gmail.com", name="Dojo Owner")
        user, account = await _upsert_user_and_account(info)

        async with factory() as db:
            await db.execute(text(f"UPDATE users SET is_admin = true WHERE id = '{user.id}'"))
            agent = Agent(
                account_id=account.id, creator_id=user.id, name="Mika",
                slug="dojo-mika", status="running", runtime_kind="fly-machine",
                runtime_ref=None,
            )
            db.add(agent)
            await db.flush()

            version_id, _ = await resolve_commercial_version(db, account.id, now)
            db.add(AgentHostingPeriod(
                agent_id=agent.id, account_id=account.id,
                starts_at=now - timedelta(days=10), ends_at=now + timedelta(days=20),
                price_credits=999, commercial_pricing_version_id=version_id,
                state="active",
            ))
            db.add(AgentCreditLimit(
                agent_id=agent.id, daily_limit_credits=75, monthly_limit_credits=800,
                warning_threshold_pct=80,
            ))

            # A week of usage: chat (2 attempts, one charge), a playbook with a
            # plugin child, a scheduled run, plus older days for the trend.
            def ev(call, *, root, rtype, service="llm", plugin=None,
                   model="claude-sonnet-5", at=now, attempt=1):
                return BillableEvent(
                    source_idempotency_key=f"dojo:{call}:{attempt}", call_id=call,
                    account_id=account.id, agent_id=agent.id, root_action_id=root,
                    root_action_type=rtype, plugin=plugin, service=service,
                    sku=f"{service}.dojo", context="agent", model=model,
                    attempt_number=attempt, event_at=at,
                )

            def rc(call, credits):
                return RatedCharge(logical_call_id=call, account_id=account.id,
                                   credits=credits, charge_status="settled")

            usage = [
                ("chat-1", "root-chat-1", "chat", 18, now - timedelta(minutes=50)),
                ("pb-1", "root-pb-1", "playbook_run", 22, now - timedelta(hours=2)),
                ("sched-1", "root-sched-1", "scheduled_run", 9, now - timedelta(hours=4)),
                ("chat-old-1", "root-old-1", "chat", 31, now - timedelta(days=2)),
                ("chat-old-2", "root-old-2", "chat", 12, now - timedelta(days=4)),
                ("bg-old-1", "root-old-3", "background_run", 26, now - timedelta(days=6)),
            ]
            for call, root, rtype, credits, at in usage:
                db.add(ev(call, root=root, rtype=rtype, at=at))
                db.add(rc(call, credits))
            # Retry attempt on chat-1: extra event, same call, same single charge.
            db.add(ev("chat-1", root="root-chat-1", rtype="chat",
                      at=now - timedelta(minutes=49), attempt=2))
            # Plugin child call under the playbook root.
            db.add(ev("pb-1-plugin", root="root-pb-1", rtype="playbook_run",
                      service="composio", plugin="whatsapp", model=None,
                      at=now - timedelta(hours=2, minutes=-1)))
            db.add(rc("pb-1-plugin", 4))

            # Matching wallet movements → statement shows a running balance.
            # No `now=` override: the trial grant's effective_at is stamped at
            # signup (after our `now` capture), and charge() only burns grants
            # with effective_at <= now — an older `now` would push all of this
            # into DEBT instead of the gift lot.
            for call, _, _, credits, _at in usage:
                await ledger.charge(db, account_id=account.id,
                                    idempotency_key=f"dojo-charge:{call}",
                                    credits=credits, agent_id=agent.id,
                                    service="llm", reason="usage")
            await ledger.charge(db, account_id=account.id,
                                idempotency_key="dojo-charge:pb-1-plugin", credits=4,
                                agent_id=agent.id, service="composio",
                                reason="usage")

            # Open limit periods so per-Luna progress has data (49 today incl.
            # 4 open exposure; 122 this month = all settled charges).
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            db.add(AgentLimitPeriod(
                agent_id=agent.id, period_kind="daily", period_start=today,
                period_end=today + timedelta(days=1),
                settled_credits=45, open_exposure_credits=4,
            ))
            db.add(AgentLimitPeriod(
                agent_id=agent.id, period_kind="monthly",
                period_start=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                period_end=now.replace(day=1) + timedelta(days=31),
                settled_credits=118, open_exposure_credits=4,
            ))
            await db.commit()
            return {"user_id": str(user.id), "account_id": str(account.id),
                    "agent_id": str(agent.id)}
    finally:
        await engine.dispose()


# ── App lifecycle ────────────────────────────────────────────────────────────

def boot_app() -> subprocess.Popen:
    env = {**os.environ,
           "CLOUD_DATABASE_URL": DB_URL,
           "CLOUD_BILLING_MODE": "enforce",
           "CLOUD_SESSION_SECRET": SESSION_SECRET,
           "CLOUD_BASE_URL": BASE,  # same-origin guard must accept the dojo port
           "CLOUD_RUNTIME": "fly-machines",
           "FLY_API_TOKEN": "dojo-invalid-token",  # present-but-bogus (039/005)
           "CLOUD_RELAY_FORWARDER": "0",
           "CLOUD_RECONCILER": "0",
           "CLOUD_BILLING_WORKER": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "cloud.main:app", "--port", str(APP_PORT),
         "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=(RESULTS / "app-billing-ui.log").open("w"), stderr=subprocess.STDOUT,
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
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # reduced_motion: the marketing site reveals sections on scroll;
            # full-page screenshots would otherwise capture unrevealed blanks.
            ctx = browser.new_context(viewport={"width": 1440, "height": 960},
                                      reduced_motion="reduce")
            page = ctx.new_page()

            # 1 — public pricing page renders packages from the API (no auth).
            page.goto(f"{BASE}/pricing", wait_until="domcontentloaded")
            expect(page.get_by_text("Free trial")).to_be_visible()
            for name in ("Hobby", "Pro", "Power"):
                expect(page.locator(".card.price .tier", has_text=name)).to_be_visible()
            expect(page.get_by_text("1,800 credits included")).to_be_visible()
            expect(page.get_by_text("1,900 credits every month")).to_be_visible()
            expect(page.get_by_text("+1,100 bonus credits monthly")).to_be_visible()
            # Bonus makes the credit value exceed the price → struck-out value.
            expect(page.locator(".amt .was", has_text="$110")).to_be_visible()
            expect(page.locator(".amt .was", has_text="$250")).to_be_visible()
            expect(page.get_by_text("$10 → 1,000 credits")).to_be_visible()
            expect(page.get_by_text("999 credits per Luna / monthly")).to_be_visible()
            assert "degrade gracefully" not in page.content().lower()
            shot(page, "10-marketing-pricing-monthly.png")
            ok("1 /pricing renders trial + 3 packages + top-ups + hosting from the API")

            # 2 — yearly toggle switches to yearly lots + gift credits.
            page.get_by_role("button", name="Yearly").click()
            expect(page.get_by_text("/mo billed yearly").first).to_be_visible()
            # Yearly gift = two months of the package's paid monthly credits.
            expect(page.get_by_text("+19,800 gift credits each year")).to_be_visible()
            shot(page, "11-marketing-pricing-yearly.png")
            ok("2 yearly toggle shows billed-yearly pricing with yearly gift credits")

            # Authenticated from here on.
            ctx.add_cookies([{"name": "luna_session",
                              "value": session_cookie(ids["user_id"], ids["account_id"]),
                              "url": BASE}])

            # 3 — dashboard header links to Billing.
            page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
            billing_link = page.get_by_role("link", name="Billing")
            expect(billing_link).to_be_visible()
            billing_link.click()
            page.wait_for_url(f"{BASE}/dashboard/billing")
            ok("3 dashboard header has a Billing link that routes to /dashboard/billing")

            # 4 — Status tab (default): trial banner, balances, source bars.
            expect(page.get_by_text("Free trial.")).to_be_visible()
            expect(page.get_by_text("Balance", exact=True).first).to_be_visible()
            # 1800 gift − 122 charged = 1678.
            expect(page.get_by_text("1,678 cr").first).to_be_visible()
            expect(page.get_by_text("Credit sources")).to_be_visible()
            for bar in ("Gift & trial credits", "Bonus credits", "Bucket credits", "Top-up credits"):
                expect(page.get_by_text(bar, exact=True)).to_be_visible()
            expect(page.get_by_text("122 used · 1,678 left of 1,800")).to_be_visible()
            shot(page, "12-billing-overview.png")
            ok("4 Status tab: trial banner, 1,678 cr balance, source bars (gift 122 used)")

            # 5 — grants table shows the gift lot with burn order.
            expect(page.get_by_text("Credit lots")).to_be_visible()
            expect(page.get_by_text("1,678 / 1,800")).to_be_visible()
            expect(page.get_by_text("#1")).to_be_visible()
            ok("5 credit lots: gift 1,678/1,800 remaining, burn order #1")

            # 6 — Usage tab: totals, trend bars, per-Luna progress.
            page.get_by_role("button", name="Usage", exact=True).click()
            expect(page.get_by_text("Used in range")).to_be_visible()
            expect(page.get_by_text("122 cr").first).to_be_visible()  # 7d default range covers all
            expect(page.get_by_text("Per-Luna limits")).to_be_visible()
            expect(page.get_by_text("Mika").first).to_be_visible()
            expect(page.get_by_text("49 / 75 cr")).to_be_visible()
            shot(page, "13-billing-usage.png")
            ok("6 usage: 122 cr in 28d, trend bars, Mika daily 49/75 with progress")

            # 7 — breakdown pivots: by Luna, then by model, then by plugin.
            expect(page.get_by_text("Where credits went")).to_be_visible()
            row = page.locator("section", has_text="Where credits went").last
            expect(row.get_by_text("Mika", exact=True)).to_be_visible()
            page.get_by_role("button", name="Model").click()
            expect(row.get_by_text("claude-sonnet-5")).to_be_visible()
            page.get_by_role("button", name="Plugin").click()
            expect(row.get_by_text("whatsapp")).to_be_visible()
            expect(row.get_by_text("4 cr")).to_be_visible()
            shot(page, "14-billing-breakdown-plugin.png")
            ok("7 breakdown pivots by Luna / model / plugin with credit bars")

            # 8 — actions: playbook groups children; chat retry counted once.
            expect(page.get_by_text("Recent actions")).to_be_visible()
            pb = page.locator("button", has_text="Playbook run").first
            expect(pb).to_be_visible()
            expect(pb.get_by_text("26 cr")).to_be_visible()  # 22 + 4 plugin child
            pb.click()
            expect(page.get_by_text("composio").first).to_be_visible()
            chat = page.locator("button", has_text="Chat").first
            expect(chat.get_by_text("18 cr")).to_be_visible()  # 2 attempts, one charge
            shot(page, "15-billing-actions-expanded.png")
            ok("8 actions: playbook 26 cr with plugin child; chat retry charged once")

            # 9 — CSV export honours the cookie + range.
            r = httpx.get(f"{BASE}/api/billing/usage/actions.csv?range=28d",
                          cookies={"luna_session": session_cookie(ids["user_id"], ids["account_id"])},
                          timeout=15)
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
            lines = r.text.strip().splitlines()
            assert lines[0] == "time,luna,action,service,status,credits"
            assert len(lines) == 7  # 6 roots + header
            ok("9 actions.csv downloads 6 rows with the frozen header")

            # 10 — Billing tab: packages disabled until 007, statement with
            # the +1,800 grant and a running balance.
            page.get_by_role("button", name="Billing", exact=True).click()
            coming = page.get_by_role("button", name="Coming soon")
            expect(coming).to_have_count(3)
            for i in range(3):
                expect(coming.nth(i)).to_be_disabled()
            # $99 tier: 9,900 paid + 1,100 bonus = $110 value struck out.
            # ("9,900 credits monthly" alone is a substring of the 19,900 row)
            expect(page.get_by_text("9,900 credits monthly + 1,100 bonus", exact=True)).to_be_visible()
            expect(page.locator("s", has_text="$110")).to_be_visible()
            expect(page.get_by_text("Statement")).to_be_visible()
            expect(page.get_by_text("+1,800")).to_be_visible()
            expect(page.get_by_text("trial gift")).to_be_visible()
            shot(page, "18-billing-tab-packages-statement.png")
            ok("10 Billing tab: 3 packages disabled until 007; statement lists the trial grant")

            # 11 — owner edits limits through the same-origin PUT (Usage tab).
            page.get_by_role("button", name="Usage", exact=True).click()
            page.locator("button[title='Edit limits']").click()
            daily_input = page.locator("input[placeholder='none']").first
            daily_input.fill("100")
            page.locator("button:has(svg.lucide-check)").click()
            expect(page.get_by_text("49 / 100 cr")).to_be_visible()
            row = run(_rows(f"SELECT daily_limit_credits FROM agent_credit_limits "
                            f"WHERE agent_id = '{ids['agent_id']}'"))[0]
            assert row[0] == 100, row
            shot(page, "16-billing-limits-edited.png")
            ok("11 limit editor PUTs daily 75→100; UI and DB agree")

            # 12 — AgentDetail Spend card shows real usage + hosting.
            page.goto(f"{BASE}/dashboard/agents/{ids['agent_id']}", wait_until="domcontentloaded")
            spend = page.locator("section", has_text="Spend").last
            expect(spend.get_by_text("This month")).to_be_visible()
            expect(spend.get_by_text("of 800 cr limit")).to_be_visible()
            expect(spend.get_by_text("active", exact=False).first).to_be_visible()
            shot(page, "17-agent-spend-card.png")
            ok("12 AgentDetail Spend card: real daily/monthly usage, limits, hosting state")

            browser.close()
    finally:
        stop_app(app)

    (RESULTS / "REPORT-billing-ui.txt").write_text("\n".join(report) + "\n")
    print(f"\nAll {len(report)} scenarios passed. Evidence in {RESULTS}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        (RESULTS / "REPORT-billing-ui.txt").write_text("\n".join(report) + "\nFAILED — see traceback\n")
        raise
    sys.exit(0)
