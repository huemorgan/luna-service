"""039/002 — admin pricing API: auth, CSRF, reasons, audit, lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cloud.billing.seed import seed_billing
from cloud.db.models import AuditLog

pytestmark = pytest.mark.asyncio

SAME_ORIGIN = {"origin": "http://localhost:8100"}  # matches Settings.base_url


async def _seed(db_session):
    await seed_billing(db_session)
    await db_session.commit()


async def _v1_id(client) -> str:
    resp = await client.get("/api/admin/pricing/versions")
    return resp.json()["versions"][-1]["id"]


# ── Auth & CSRF ──────────────────────────────────────────────────────────────

async def test_pricing_admin_requires_admin(regular_client, anon_client):
    assert (await regular_client.get("/api/admin/pricing/versions")).status_code == 403
    assert (await anon_client.get("/api/admin/pricing/versions")).status_code == 401


async def test_cross_origin_mutation_rejected(admin_client, db_session):
    await _seed(db_session)
    v1 = await _v1_id(admin_client)
    resp = await admin_client.post(
        f"/api/admin/pricing/versions/{v1}/clone",
        json={}, headers={"origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert "Cross-origin" in resp.json()["detail"]
    # Referer alone is enough to be judged (Origin-less browsers).
    resp = await admin_client.post(
        f"/api/admin/pricing/versions/{v1}/clone",
        json={}, headers={"referer": "https://evil.example/admin/pricing"},
    )
    assert resp.status_code == 403


async def test_same_origin_and_headerless_mutations_pass(admin_client, db_session):
    await _seed(db_session)
    v1 = await _v1_id(admin_client)
    assert (await admin_client.post(
        f"/api/admin/pricing/versions/{v1}/clone", json={}, headers=SAME_ORIGIN,
    )).status_code == 200
    # No Origin/Referer (curl, server-to-server) — not a CSRF vector.
    assert (await admin_client.post(
        f"/api/admin/pricing/versions/{v1}/clone", json={},
    )).status_code == 200


async def test_cross_origin_reads_still_allowed(admin_client, db_session):
    await _seed(db_session)
    resp = await admin_client.get(
        "/api/admin/pricing/versions", headers={"origin": "https://evil.example"}
    )
    assert resp.status_code == 200


# ── Reason requirement ───────────────────────────────────────────────────────

async def test_financial_actions_require_reason(admin_client, db_session):
    await _seed(db_session)
    v1 = await _v1_id(admin_client)
    for path in (f"/api/admin/pricing/versions/{v1}/publish",
                 f"/api/admin/pricing/versions/{v1}/retire"):
        for body in ({}, {"reason": "  "}):
            resp = await admin_client.post(path, json=body)
            assert resp.status_code == 400
            assert "reason" in resp.json()["detail"].lower()


# ── Version lifecycle through the API ────────────────────────────────────────

async def test_clone_edit_publish_retire_flow(admin_client, db_session):
    await _seed(db_session)
    v1 = await _v1_id(admin_client)

    resp = await admin_client.post(
        f"/api/admin/pricing/versions/{v1}/clone",
        json={"name": "v2 draft", "notes": "raise trial"},
    )
    assert resp.status_code == 200
    draft = resp.json()
    assert draft["status"] == "draft" and draft["parent_version_id"] == v1

    config = draft["config"]
    config["trial"]["gift_credits"] = 2_000
    resp = await admin_client.put(
        f"/api/admin/pricing/versions/{draft['id']}", json={"config": config}
    )
    assert resp.status_code == 200

    # Invalid config rejected with the validator's message.
    bad = dict(config, credit_value_micro_usd=1)
    resp = await admin_client.put(
        f"/api/admin/pricing/versions/{draft['id']}", json={"config": bad}
    )
    assert resp.status_code == 400

    resp = await admin_client.get(f"/api/admin/pricing/versions/{draft['id']}")
    body = resp.json()
    assert body["diff_vs_parent"]["trial.gift_credits"] == {"from": 1_800, "to": 2_000}
    assert body["uncovered_models"] == []

    resp = await admin_client.post(
        f"/api/admin/pricing/versions/{draft['id']}/publish",
        json={"reason": "trial bump per plan"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"

    # Published versions are immutable through the API too.
    resp = await admin_client.put(
        f"/api/admin/pricing/versions/{draft['id']}", json={"name": "nope"}
    )
    assert resp.status_code == 400

    resp = await admin_client.post(
        f"/api/admin/pricing/versions/{v1}/retire", json={"reason": "superseded by v2"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "retired"


async def test_lifecycle_writes_audit_rows(admin_client, db_session):
    await _seed(db_session)
    v1 = await _v1_id(admin_client)
    await admin_client.post(f"/api/admin/pricing/versions/{v1}/clone", json={})
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "pricing.version.clone")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor_user_id is not None


async def test_publish_audit_carries_reason(admin_client, db_session):
    await _seed(db_session)
    v1 = await _v1_id(admin_client)
    resp = await admin_client.post(f"/api/admin/pricing/versions/{v1}/clone", json={})
    draft_id = resp.json()["id"]
    await admin_client.post(
        f"/api/admin/pricing/versions/{draft_id}/publish", json={"reason": "launch"}
    )
    row = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "pricing.version.publish")
    )).scalar_one()
    assert row.metadata_ == {"reason": "launch"}
    assert row.before_state["status"] == "draft"
    assert row.after_state["status"] == "published"


# ── Overview ─────────────────────────────────────────────────────────────────

async def test_overview_shape(admin_client, db_session):
    await _seed(db_session)
    resp = await admin_client.get("/api/admin/pricing/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_version"]["version_number"] == 1
    assert body["version_status_counts"] == {"published": 1}
    assert body["customer_liability_credits"] == 0
    assert body["uncovered_debt_credits"] == 0
    assert body["dead_billing_jobs"] == 0
    assert body["needs_reconciliation_holds"] == 0
    assert body["assigned_accounts"] == 0


async def test_overview_survives_unseeded_db(admin_client):
    resp = await admin_client.get("/api/admin/pricing/overview")
    assert resp.status_code == 200
    assert resp.json()["default_version"] is None


# ── Assignments & rollouts through the API ───────────────────────────────────

async def test_manual_assignment_flow(admin_client, db_session, account):
    await _seed(db_session)
    v1 = await _v1_id(admin_client)
    resp = await admin_client.post("/api/admin/pricing/assignments", json={
        "account_id": str(account.id), "version_id": v1, "reason": "test pin",
    })
    assert resp.status_code == 200
    assert resp.json()["source"] == "manual_test"

    resp = await admin_client.get(f"/api/admin/pricing/accounts/{account.id}/assignments")
    assert len(resp.json()["assignments"]) == 1

    # Unknown account → 404; missing reason → 400.
    resp = await admin_client.post("/api/admin/pricing/assignments", json={
        "account_id": str(uuid.uuid4()), "version_id": v1, "reason": "x",
    })
    assert resp.status_code == 404
    resp = await admin_client.post("/api/admin/pricing/assignments", json={
        "account_id": str(account.id), "version_id": v1,
    })
    assert resp.status_code == 400


async def test_rollout_create_and_list(admin_client, db_session):
    await _seed(db_session)
    v1 = await _v1_id(admin_client)
    effective = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = await admin_client.post("/api/admin/pricing/rollouts", json={
        "version_id": v1, "audience": "new_accounts",
        "effective_at": effective, "reason": "flip default",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "scheduled"

    resp = await admin_client.post("/api/admin/pricing/rollouts", json={
        "version_id": v1, "audience": "everyone", "reason": "x",
    })
    assert resp.status_code == 400

    resp = await admin_client.get("/api/admin/pricing/rollouts")
    assert len(resp.json()["rollouts"]) == 1


# ── Provider costs through the API ───────────────────────────────────────────

async def test_provider_cost_draft_and_publish(admin_client, db_session):
    await _seed(db_session)
    resp = await admin_client.post("/api/admin/pricing/provider-costs", json={
        "rates": [{
            "provider": "anthropic", "sku": "claude-opus-4-6",
            "dimension": "input_tokens", "unit": "mtok",
            "rate_numerator": 6, "rate_denominator": 1,
        }],
        "notes": "opus price change",
    })
    assert resp.status_code == 200
    draft = resp.json()
    assert draft["status"] == "draft" and draft["version_number"] == 2

    resp = await admin_client.post(
        f"/api/admin/pricing/provider-costs/{draft['id']}/publish", json={}
    )
    assert resp.status_code == 400  # reason required

    resp = await admin_client.post(
        f"/api/admin/pricing/provider-costs/{draft['id']}/publish",
        json={"reason": "vendor repriced"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"

    resp = await admin_client.get(f"/api/admin/pricing/provider-costs/{draft['id']}")
    rates = resp.json()["rates"]
    assert rates == [{
        "provider": "anthropic", "sku": "claude-opus-4-6",
        "dimension": "input_tokens", "unit": "mtok",
        "rate_numerator": 6, "rate_denominator": 1,
        "quality": "estimated", "source_url": None,
    }]


async def test_provider_cost_invalid_rates_rejected(admin_client, db_session):
    await _seed(db_session)
    dup = {
        "provider": "anthropic", "sku": "claude-opus-4-6",
        "dimension": "input_tokens", "unit": "mtok",
        "rate_numerator": 6, "rate_denominator": 1,
    }
    resp = await admin_client.post("/api/admin/pricing/provider-costs", json={
        "rates": [dup, dict(dup)],
    })
    assert resp.status_code == 400  # duplicate (provider, sku, dimension)
    resp = await admin_client.post("/api/admin/pricing/provider-costs", json={
        "rates": [dict(dup, rate_denominator=0)],
    })
    assert resp.status_code == 400


# ── Enforcement overrides (039/010) ──────────────────────────────────────────

async def test_enforcement_state_empty(admin_client):
    resp = await admin_client.get("/api/admin/pricing/enforcement")
    assert resp.status_code == 200
    body = resp.json()
    assert body["global_mode"] == "off"
    assert body["modes"] == ["off", "observe", "shadow", "enforce"]
    assert body["overrides"] == []


async def test_enforcement_requires_admin(regular_client, anon_client):
    assert (await regular_client.get("/api/admin/pricing/enforcement")).status_code == 403
    assert (await anon_client.get("/api/admin/pricing/enforcement")).status_code == 401
    resp = await regular_client.post(
        "/api/admin/pricing/enforcement/overrides",
        json={"account_ids": [str(uuid.uuid4())], "mode": "enforce", "reason": "x"},
        headers=SAME_ORIGIN,
    )
    assert resp.status_code == 403


async def test_override_set_list_clear_with_audit(admin_client, db_session, account):
    set_resp = await admin_client.post(
        "/api/admin/pricing/enforcement/overrides",
        json={"account_ids": [str(account.id)], "mode": "enforce",
              "reason": "canary rollout step 7"},
        headers=SAME_ORIGIN,
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["applied"] == [
        {"account_id": str(account.id), "slug": "test-account", "mode": "enforce"}
    ]

    state = (await admin_client.get("/api/admin/pricing/enforcement")).json()
    assert len(state["overrides"]) == 1
    ov = state["overrides"][0]
    assert ov["mode"] == "enforce"
    assert ov["effective_mode"] == "enforce"  # global off, override wins
    assert ov["slug"] == "test-account" and ov["set_at"] is not None

    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "pricing.enforcement.override")
    )).scalars().all()
    assert len(audits) == 1
    assert audits[0].before_state == {"mode": None}
    assert audits[0].after_state == {"mode": "enforce"}
    assert audits[0].metadata_["reason"] == "canary rollout step 7"

    clear_resp = await admin_client.post(
        "/api/admin/pricing/enforcement/overrides",
        json={"account_ids": [str(account.id)], "mode": None, "reason": "rollback"},
        headers=SAME_ORIGIN,
    )
    assert clear_resp.status_code == 200
    state = (await admin_client.get("/api/admin/pricing/enforcement")).json()
    assert state["overrides"] == []


async def test_override_requires_reason_and_valid_mode(admin_client, account):
    no_reason = await admin_client.post(
        "/api/admin/pricing/enforcement/overrides",
        json={"account_ids": [str(account.id)], "mode": "enforce", "reason": "  "},
        headers=SAME_ORIGIN,
    )
    assert no_reason.status_code == 400

    bad_mode = await admin_client.post(
        "/api/admin/pricing/enforcement/overrides",
        json={"account_ids": [str(account.id)], "mode": "off", "reason": "x"},
        headers=SAME_ORIGIN,
    )
    assert bad_mode.status_code == 400


async def test_override_unknown_account_404(admin_client, account):
    resp = await admin_client.post(
        "/api/admin/pricing/enforcement/overrides",
        json={"account_ids": [str(uuid.uuid4())], "mode": "shadow", "reason": "x"},
        headers=SAME_ORIGIN,
    )
    assert resp.status_code == 404


async def test_accounts_search(admin_client, account):
    hit = (await admin_client.get("/api/admin/pricing/accounts/search?q=test-acc")).json()
    assert [a["slug"] for a in hit["accounts"]] == ["test-account"]
    assert hit["accounts"][0]["override"] is None

    miss = (await admin_client.get("/api/admin/pricing/accounts/search?q=zzz-nope")).json()
    assert miss["accounts"] == []
