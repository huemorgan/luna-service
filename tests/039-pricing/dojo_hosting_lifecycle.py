"""039/005 dojo — hosting lifecycle against real Postgres.

End-to-end pieces SQLite tests can't give us: the real uvicorn app with the
billing worker + maintenance loop, real migrations on PG (0004), the real
signup transaction, and renewal by time-travel (UPDATE ends_at into the past,
watch the live sweep act).

Provisioning is expected to FAIL here (CLOUD_RUNTIME=fly-machines with an
invalid FLY_API_TOKEN — Fly rejects every call) — that is scenario 4's point:
a failed provision retries durably and never silently releases the hold. The
token must be present-but-bogus, not absent: start_agent constructs the
runtime outside its try/except, so a missing token would 500 and roll back
the scenario-8 recovery charge.

Self-contained: scratch DB dojo039host on the docker PG at :5435.
Run: `python3 tests/039-pricing/dojo_hosting_lifecycle.py`.
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PG_ADMIN = "postgresql+asyncpg://luna:luna@localhost:5435/postgres"
DB_NAME = "dojo039host"
DB_URL = f"postgresql+asyncpg://luna:luna@localhost:5435/{DB_NAME}"
APP_PORT = 8104
BASE = f"http://127.0.0.1:{APP_PORT}"
SESSION_SECRET = "dojo-secret"

RESULTS = Path(__file__).parent / "results" / f"{date.today().isoformat()}-local"
RESULTS.mkdir(parents=True, exist_ok=True)
report: list[str] = []


def ok(name: str) -> None:
    report.append(f"PASS  {name}")
    print(report[-1], flush=True)


def cookie(user_id: str, account_id: str) -> dict:
    payload = json.dumps({"user_id": user_id, "account_id": account_id})
    return {"luna_session": URLSafeTimedSerializer(SESSION_SECRET).dumps(payload)}


# ── DB helpers ────────────────────────────────────────────────────────────────

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


def run(coro):
    return asyncio.run(coro)


def wait_for(describe: str, probe, *, timeout: float = 90.0, interval: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for: {describe}")


# ── Seed ─────────────────────────────────────────────────────────────────────

async def seed() -> dict:
    """Real signup for account A; direct rows for the lifecycle accounts."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cloud.api.auth_routes import _upsert_user_and_account
    from cloud.auth.identity import UserInfo
    from cloud.billing import ledger
    from cloud.billing.models import AgentHostingPeriod
    from cloud.billing.rating import resolve_commercial_version
    from cloud.billing.seed import seed_billing
    from cloud.db.models import Account, Agent, Membership

    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as db:
            await seed_billing(db)
            await db.commit()

        # Scenario 1: the REAL signup transaction (assignment + trial gift),
        # twice — the second login must not duplicate the gift.
        info = UserInfo(sub="dojo-sub-1", email="vaselin@gmail.com", name="Dojo Owner")
        user, account_a = await _upsert_user_and_account(info)
        await _upsert_user_and_account(info)

        out = {"user_id": str(user.id), "A": str(account_a.id)}
        async with factory() as db:
            await db.execute(text(
                f"UPDATE users SET is_admin = true WHERE id = '{user.id}'"
            ))

            # B: broke + active period already past its end → payment_due path.
            # E: funded, anchored on the 31st, period May 31 → Jun 30 (clamped)
            #    already past due — exactly ONE renewal lands in the future
            #    (Jun 30 → Jul 31, anchor restored). Older dates would chain
            #    renewals on every 60s sweep until the balance ran dry.
            # C: funded + current period → soft-delete path.
            for label, credits, starts, ends in (
                ("b", 0,
                 datetime(2026, 6, 1, tzinfo=timezone.utc),
                 now - timedelta(days=1)),
                ("e", 1800,
                 datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
                 datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)),
                ("c", 1800, now, now + timedelta(days=20)),
            ):
                acc = Account(slug=f"dojo-{label}", name=f"Dojo {label.upper()}",
                              created_by=user.id)
                db.add(acc)
                await db.flush()
                db.add(Membership(account_id=acc.id, user_id=user.id, role="owner"))
                agent = Agent(
                    account_id=acc.id, creator_id=user.id, name=f"Luna {label.upper()}",
                    slug=f"dojo-{label}-luna", status="stopped",
                    runtime_kind="fly-machine",
                    runtime_ref="dojo-no-such-machine" if label == "b" else None,
                )
                db.add(agent)
                await db.flush()
                await ledger.ensure_billing_account(db, acc.id)
                if credits:
                    await ledger.create_grant(
                        db, account_id=acc.id, source_type="gift",
                        source_key=f"dojo:{label}", credits=credits,
                        visible_category="gift", effective_at=now - timedelta(days=200),
                        expires_at=None, now=now,
                    )
                version_id, _ = await resolve_commercial_version(db, acc.id, now)
                db.add(AgentHostingPeriod(
                    agent_id=agent.id, account_id=acc.id,
                    starts_at=starts, ends_at=ends, price_credits=999,
                    commercial_pricing_version_id=version_id, state="active",
                ))
                out[label.upper()] = str(acc.id)
                out[f"{label.upper()}_agent"] = str(agent.id)
            await db.commit()
        return out
    finally:
        await engine.dispose()


# ── App lifecycle ────────────────────────────────────────────────────────────

def boot_app(mode: str) -> subprocess.Popen:
    env = {**os.environ,
           "CLOUD_DATABASE_URL": DB_URL,
           "CLOUD_BILLING_MODE": mode,
           "CLOUD_SESSION_SECRET": SESSION_SECRET,
           "CLOUD_RUNTIME": "fly-machines",
           # Bogus on purpose: runtime constructs, every Fly call gets 401.
           "FLY_API_TOKEN": "dojo-invalid-token",
           "CLOUD_RELAY_FORWARDER": "0",
           "CLOUD_RECONCILER": "0",
           "CLOUD_BILLING_WORKER": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "cloud.main:app", "--port", str(APP_PORT),
         "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=(RESULTS / f"app-hosting-{mode}.log").open("w"), stderr=subprocess.STDOUT,
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


# ── Scenarios ────────────────────────────────────────────────────────────────

def main() -> None:
    os.environ["CLOUD_DATABASE_URL"] = DB_URL

    run(_exec(PG_ADMIN, f'DROP DATABASE IF EXISTS {DB_NAME} (FORCE)',
              f'CREATE DATABASE {DB_NAME}', autocommit=True))
    subprocess.run([sys.executable, "-m", "cloud.db.migrate"], cwd=str(ROOT),
                   env={**os.environ, "CLOUD_DATABASE_URL": DB_URL}, check=True,
                   capture_output=True)
    cols = run(_rows("SELECT column_name FROM information_schema.columns "
                     "WHERE table_name = 'agents' AND column_name = 'deleted_at'"))
    assert cols, "0004 soft-delete column missing"
    ok("0 scratch DB migrated to head on PG (0004 agents.deleted_at present)")

    ids = run(seed())
    user_id = ids["user_id"]

    gifts = run(_rows(f"SELECT original_credits, source_key FROM credit_grants "
                      f"WHERE account_id = '{ids['A']}'"))
    assert len(gifts) == 1 and gifts[0][0] == 1800, gifts
    assert gifts[0][1] == f"trial:{ids['A']}"
    ok("1 real signup path: assignment + 1800 trial gift exactly once across two logins")

    # ── enforce ──────────────────────────────────────────────────────────
    app = boot_app("enforce")
    try:
        ck_a = cookie(user_id, ids["A"])

        # Create Luna on the trial account: durable period + hold + job.
        r = httpx.post(f"{BASE}/api/agents", json={"name": "Dojo Luna"},
                       cookies=ck_a, timeout=30)
        assert r.status_code == 201, r.text
        a_agent = r.json()["id"]
        period = run(_rows(f"SELECT id, state, price_credits FROM agent_hosting_periods "
                           f"WHERE agent_id = '{a_agent}'"))[0]
        assert period[1] == "pending" and period[2] == 999
        hold = run(_rows(f"SELECT status, estimated_credits FROM billing_holds "
                         f"WHERE operation_id = 'hosting:{period[0]}'"))[0]
        assert hold[0] == "open" and hold[1] == 999
        limits = run(_rows(f"SELECT daily_limit_credits, monthly_limit_credits "
                           f"FROM agent_credit_limits WHERE agent_id = '{a_agent}'"))[0]
        assert (limits[0], limits[1]) == (75, 800)
        ok("2 enforce create: pending period + open 999 hold + trial limits 75/800")

        # Trial cap: one active Luna.
        r = httpx.post(f"{BASE}/api/agents", json={"name": "Second"},
                       cookies=ck_a, timeout=30)
        assert r.status_code == 402 and r.json()["detail"]["code"] == "active_luna_limit"
        ok("3 enforce create #2: 402 active_luna_limit (trial cap 1)")

        # Provisioning fails (Fly rejects the bogus token) → durable retry.
        job = wait_for(
            "provision job to fail at least once",
            lambda: (run(_rows(
                f"SELECT attempts, status, last_error FROM billing_outbox "
                f"WHERE dedupe_key = 'hostprov:{period[0]}' AND attempts >= 1"
            )) or [None])[0],
            timeout=30, interval=2,
        )
        assert job[1] in ("pending", "running", "dead"), job
        hold = run(_rows(f"SELECT status FROM billing_holds "
                         f"WHERE operation_id = 'hosting:{period[0]}'"))[0]
        assert hold[0] == "open"  # never silently released on failure
        r = httpx.post(f"{BASE}/api/agents/{a_agent}/retry", cookies=ck_a, timeout=30)
        assert r.status_code == 200, r.text
        job2 = run(_rows(f"SELECT attempts, status FROM billing_outbox "
                         f"WHERE dedupe_key = 'hostprov:{period[0]}'"))[0]
        assert job2[1] in ("pending", "running")  # worker may grab it instantly
        ok("4 provision failure: job retries durably, hold stays open; user retry requeues")

        # Maintenance sweep (runs at boot + every 60s): E renews with the
        # monthly-anchor clamp; B goes payment_due + durable suspend.
        renewed = wait_for(
            "E's renewal by the live maintenance loop",
            lambda: run(_rows(
                f"SELECT starts_at, ends_at, charge_transaction_id "
                f"FROM agent_hosting_periods WHERE account_id = '{ids['E']}' "
                f"AND state = 'active' AND starts_at > '2026-06-05'"
            )),
        )[0]
        assert renewed[0].date().isoformat() == "2026-06-30"  # seamless from old end
        assert renewed[1].date().isoformat() == "2026-07-31"  # anchor day 31 restored
        assert renewed[2] is not None
        bal_e = run(_rows(f"SELECT posted_balance_credits FROM account_balance_projections "
                          f"WHERE account_id = '{ids['E']}'"))[0][0]
        assert bal_e == 1800 - 999, bal_e
        ok("5 live renewal: Jun 30 → Jul 31 anchor clamp, 999 charged (1800 → 801)")

        due = wait_for(
            "B's period to go payment_due",
            lambda: run(_rows(
                f"SELECT id FROM agent_hosting_periods WHERE account_id = '{ids['B']}' "
                f"AND state = 'payment_due'"
            )),
        )[0]
        susp = run(_rows(f"SELECT status FROM billing_outbox "
                         f"WHERE dedupe_key = 'hostsusp:{due[0]}'"))
        assert susp, "suspend job missing"
        r = httpx.post(f"{BASE}/api/agents/{ids['B_agent']}/start",
                       cookies=cookie(user_id, ids["B"]), timeout=30)
        assert r.status_code == 402 and r.json()["detail"]["code"] == "hosting_payment_due"
        ok("6 unpayable renewal: payment_due + durable suspend; start blocked with 402")

        # Admin gift: reason-gated, audited, then funds B's recovery.
        r = httpx.post(f"{BASE}/api/admin/pricing/gifts",
                       json={"account_id": ids["B"], "credits": 1200},
                       cookies=ck_a, timeout=30)
        assert r.status_code == 400  # no reason, no money movement
        r = httpx.post(f"{BASE}/api/admin/pricing/gifts",
                       json={"account_id": ids["B"], "credits": 1200,
                             "reason": "dojo recovery gift"},
                       cookies=ck_a, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["expires_at"] is not None  # gift_default_days from config
        audit = run(_rows("SELECT action FROM audit_log WHERE action = 'pricing.gift.create'"))
        assert audit
        ok("7 admin gift: reason required, audit row written, 1200 credits granted")

        # Recovery on start: fresh month charged, block lifted. (The runtime
        # start itself fails — no Fly here — which must not undo the billing.)
        r = httpx.post(f"{BASE}/api/agents/{ids['B_agent']}/start",
                       cookies=cookie(user_id, ids["B"]), timeout=30)
        assert r.status_code == 200, r.text
        states = run(_rows(f"SELECT state, count(*) FROM agent_hosting_periods "
                           f"WHERE account_id = '{ids['B']}' GROUP BY state"))
        assert dict(states).get("payment_due") is None, states
        bal_b = run(_rows(f"SELECT posted_balance_credits FROM account_balance_projections "
                          f"WHERE account_id = '{ids['B']}'"))[0][0]
        assert bal_b == 1200 - 999, bal_b
        ok("8 recovery: balance covers a fresh month → charged 999, payment_due cleared")

        # Soft delete: tombstone, period ended, money rows intact, teardown ran.
        r = httpx.delete(f"{BASE}/api/agents/{ids['C_agent']}",
                         cookies=cookie(user_id, ids["C"]), timeout=30)
        assert r.status_code == 200, r.text
        row = run(_rows(f"SELECT deleted_at, status FROM agents "
                        f"WHERE id = '{ids['C_agent']}'"))[0]
        assert row[0] is not None and row[1] == "stopped"
        assert run(_rows(f"SELECT state FROM agent_hosting_periods "
                         f"WHERE agent_id = '{ids['C_agent']}'"))[0][0] == "ended"
        wait_for(
            "teardown job to succeed",
            lambda: run(_rows(
                f"SELECT id FROM billing_outbox WHERE dedupe_key = "
                f"'teardown:{ids['C_agent']}' AND status = 'succeeded'"
            )),
            timeout=30, interval=2,
        )
        r = httpx.get(f"{BASE}/api/agents", cookies=cookie(user_id, ids["C"]), timeout=30)
        assert r.json() == []  # invisible to the user, alive in the ledger
        grants_c = run(_rows(f"SELECT count(*) FROM credit_grants "
                             f"WHERE account_id = '{ids['C']}'"))[0][0]
        assert grants_c == 1
        ok("9 soft delete: tombstone + ended period + teardown succeeded; billing rows kept")
    finally:
        stop_app(app)

    # ── observe ──────────────────────────────────────────────────────────
    app = boot_app("observe")
    try:
        # Cap would block, but observe only logs; lifecycle rows written, no hold.
        holds_before = run(_rows("SELECT count(*) FROM billing_holds"))[0][0]
        r = httpx.post(f"{BASE}/api/agents", json={"name": "Observe Luna"},
                       cookies=cookie(user_id, ids["A"]), timeout=30)
        assert r.status_code == 201, r.text
        o_agent = r.json()["id"]
        period = run(_rows(f"SELECT state FROM agent_hosting_periods "
                           f"WHERE agent_id = '{o_agent}'"))[0]
        assert period[0] == "pending"
        holds_after = run(_rows("SELECT count(*) FROM billing_holds"))[0][0]
        assert holds_after == holds_before  # no money movement outside enforce
        ok("10 observe: cap only logged, period row written, zero holds")
    finally:
        stop_app(app)

    (RESULTS / "REPORT-hosting.txt").write_text("\n".join(report) + "\n")
    print(f"\nAll {len(report)} scenarios passed. Evidence in {RESULTS}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        (RESULTS / "REPORT-hosting.txt").write_text("\n".join(report) + "\nFAILED — see traceback\n")
        raise
