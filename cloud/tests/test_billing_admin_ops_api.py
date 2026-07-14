"""039/009 — admin API: ops drill-downs and simulation lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import cloud.billing.simulator  # noqa: F401 — registers the pricing_sim handler
from cloud.billing import worker
from cloud.billing.ledger import ensure_billing_account
from cloud.billing.models import BillableEvent, PricingSimulation
from cloud.billing.seed import seed_billing
from cloud.db.models import AuditLog

pytestmark = pytest.mark.asyncio

SAME_ORIGIN = {"origin": "http://localhost:8100"}
NOW = datetime.now(timezone.utc)


async def _seed_usage(db_session, account):
    await seed_billing(db_session)
    await ensure_billing_account(db_session, account.id)
    db_session.add(BillableEvent(
        source_idempotency_key="ops-op-1:1", call_id="ops-op-1",
        account_id=account.id, service="llm", sku="llm_call", context="agent",
        provider="openai", model="gpt-4o", attempt_number=1,
        quantity_json={"input_tokens": 100}, vendor_cost_micro_usd=25_000,
        cost_source="provider_usage", status="recorded",
        event_at=NOW - timedelta(days=1),
    ))
    await db_session.commit()


async def _version_ids(client):
    resp = await client.get("/api/admin/pricing/versions")
    v1 = resp.json()["versions"][-1]["id"]
    return v1, v1  # baseline == candidate is a valid A/A run


# ── Ops ──────────────────────────────────────────────────────────────────────

async def test_ops_requires_admin(regular_client, anon_client):
    assert (await regular_client.get("/api/admin/pricing/ops")).status_code == 403
    assert (await anon_client.get("/api/admin/pricing/ops")).status_code == 401


async def test_ops_snapshot_and_invariants(admin_client, db_session, account):
    await _seed_usage(db_session, account)
    resp = await admin_client.get("/api/admin/pricing/ops")
    assert resp.status_code == 200
    snapshot = resp.json()
    for key in ("holds", "worker", "webhooks", "hosting", "clawback",
                "stripe_bindings", "heartbeats", "would_block"):
        assert key in snapshot

    resp = await admin_client.get("/api/admin/pricing/ops/invariants")
    assert resp.status_code == 200
    invariants = resp.json()
    assert invariants["trial_balance"]["ok"]
    assert invariants["projection_drift"]["ok"]
    assert invariants["grant_remainders"]["ok"]


async def test_ops_alert_evaluate_and_list(admin_client, db_session, account):
    await _seed_usage(db_session, account)
    # A dead stripe job is the canonical critical signal.
    job = await worker.enqueue(db_session, job_type="stripe.grant_for_invoice",
                               payload={}, max_attempts=1)
    job.attempts = 1
    await worker.fail_job(db_session, job, error="boom", now=NOW)
    await db_session.commit()

    resp = await admin_client.post("/api/admin/pricing/ops/alerts/evaluate",
                                   json={}, headers=SAME_ORIGIN)
    assert resp.status_code == 200
    active = resp.json()["active"]
    assert any(a["alert_key"] == "dead_money_jobs" for a in active)

    resp = await admin_client.get("/api/admin/pricing/ops/alerts")
    alerts = resp.json()["alerts"]
    row = next(a for a in alerts if a["alert_key"] == "dead_money_jobs")
    assert row["severity"] == "critical" and row["status"] == "active"


# ── Simulations ──────────────────────────────────────────────────────────────

async def test_simulation_lifecycle_via_api(admin_client, db_session, account):
    await _seed_usage(db_session, account)
    baseline, candidate = await _version_ids(admin_client)

    resp = await admin_client.post("/api/admin/pricing/simulations", json={
        "baseline_version_id": baseline, "candidate_version_id": candidate,
        "transforms": {"cost_multiplier": "0.50"},
    }, headers=SAME_ORIGIN)
    assert resp.status_code == 200
    sim = resp.json()
    assert sim["state"] == "pending" and sim["event_count"] == 1

    # The durable job runs it.
    done = await worker.run_once(db_session, worker_id="test")
    assert done == 1
    resp = await admin_client.get(f"/api/admin/pricing/simulations/{sim['id']}")
    detail = resp.json()
    assert detail["state"] == "succeeded"
    assert detail["result"]["baseline"]["credits"] == 4
    assert detail["result"]["candidate"]["credits"] == 3  # half-cost transform

    # CSV export.
    resp = await admin_client.get(f"/api/admin/pricing/simulations/{sim['id']}/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert str(account.id) in resp.text

    # Rerun by manifest → identical result hash after the worker runs it.
    resp = await admin_client.post(
        f"/api/admin/pricing/simulations/{sim['id']}/rerun",
        json={}, headers=SAME_ORIGIN)
    assert resp.status_code == 200
    rerun_id = resp.json()["id"]
    await worker.run_once(db_session, worker_id="test")
    resp = await admin_client.get(f"/api/admin/pricing/simulations/{rerun_id}")
    assert (resp.json()["result"]["result_hash"]
            == detail["result"]["result_hash"])

    # Cancel is rejected once succeeded.
    resp = await admin_client.post(
        f"/api/admin/pricing/simulations/{sim['id']}/cancel",
        json={}, headers=SAME_ORIGIN)
    assert resp.status_code == 409

    # List shows both runs, audit rows exist.
    resp = await admin_client.get("/api/admin/pricing/simulations")
    assert len(resp.json()["simulations"]) == 2
    actions = (await db_session.execute(select(AuditLog.action))).scalars().all()
    assert "pricing.simulation.create" in actions
    assert "pricing.simulation.rerun" in actions


async def test_simulation_validation_errors_are_400(admin_client, db_session, account):
    await _seed_usage(db_session, account)
    baseline, candidate = await _version_ids(admin_client)
    resp = await admin_client.post("/api/admin/pricing/simulations", json={
        "baseline_version_id": baseline, "candidate_version_id": candidate,
        "replay_mode": "wallet_constrained",
        "transforms": {"volume_multiplier": "2"},
    }, headers=SAME_ORIGIN)
    assert resp.status_code == 400
    assert "full_demand" in resp.json()["detail"]


async def test_pending_simulation_cancel_and_csv_409(admin_client, db_session, account):
    await _seed_usage(db_session, account)
    baseline, candidate = await _version_ids(admin_client)
    resp = await admin_client.post("/api/admin/pricing/simulations", json={
        "baseline_version_id": baseline, "candidate_version_id": candidate,
    }, headers=SAME_ORIGIN)
    sim_id = resp.json()["id"]

    # No result yet → CSV conflicts.
    resp = await admin_client.get(f"/api/admin/pricing/simulations/{sim_id}/csv")
    assert resp.status_code == 409

    resp = await admin_client.post(
        f"/api/admin/pricing/simulations/{sim_id}/cancel",
        json={}, headers=SAME_ORIGIN)
    assert resp.status_code == 200
    assert resp.json()["state"] == "cancelled"

    # The queued job runs but never publishes a result.
    await worker.run_once(db_session, worker_id="test")
    row = await db_session.get(PricingSimulation, uuid.UUID(sim_id))
    await db_session.refresh(row)
    assert row.state == "cancelled" and row.result is None
