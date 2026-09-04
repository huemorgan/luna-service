"""Plan 088 — service API keys: management endpoints + scoped feedback access."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cloud.auth.api_keys import generate_key
from cloud.db.models import AuditLog, ServiceApiKey


async def _mint(admin_client, **overrides):
    payload = {"name": "test-key", "scopes": ["feedback:full"], **overrides}
    res = await admin_client.post("/api/admin/service-keys", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


async def _ticket(anon_client, db_session, sample_agent):
    from cloud.gateway.tokens import issue_token
    tok = await issue_token(db_session, sample_agent.id)
    await db_session.commit()
    res = await anon_client.post(
        "/api/agent/feedback/tickets",
        headers={"Authorization": f"Bearer {tok}"},
        json={"origin": "user", "category": "bug", "title": "Broken thing",
              "body": "It broke."},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ── Management API (cookie-only) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_returns_secret_once_and_list_hides_it(admin_client):
    created = await _mint(admin_client)
    assert created["key"].startswith("lsk_") and len(created["key"]) > 20
    assert created["state"] == "active"
    assert created["key_prefix"] == created["key"][:12]

    res = await admin_client.get("/api/admin/service-keys")
    assert res.status_code == 200
    rows = res.json()["keys"]
    assert len(rows) == 1
    assert "key" not in rows[0]
    assert rows[0]["key_prefix"] == created["key_prefix"]


@pytest.mark.asyncio
async def test_create_validates_scopes_and_expiry(admin_client):
    res = await admin_client.post(
        "/api/admin/service-keys",
        json={"name": "x", "scopes": ["nope:full"]},
    )
    assert res.status_code == 422
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    res = await admin_client.post(
        "/api/admin/service-keys",
        json={"name": "x", "scopes": ["feedback:full"], "expires_at": past},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_scope_catalog(admin_client):
    res = await admin_client.get("/api/admin/service-keys/scopes")
    assert res.status_code == 200
    scopes = {s["scope"] for s in res.json()["scopes"]}
    assert "feedback:full" in scopes


@pytest.mark.asyncio
async def test_revoke_and_audit(admin_client, db_session):
    created = await _mint(admin_client)
    res = await admin_client.post(f"/api/admin/service-keys/{created['id']}/revoke")
    assert res.status_code == 200 and res.json()["state"] == "revoked"
    # idempotent
    res = await admin_client.post(f"/api/admin/service-keys/{created['id']}/revoke")
    assert res.status_code == 200 and res.json()["state"] == "revoked"
    actions = (await db_session.execute(select(AuditLog.action))).scalars().all()
    assert actions.count("service_key.create") == 1
    assert actions.count("service_key.revoke") == 1


@pytest.mark.asyncio
async def test_management_requires_cookie_not_key(admin_client, anon_client):
    created = await _mint(admin_client)
    headers = {"x-api-key": created["key"]}
    for method, path in [
        ("get", "/api/admin/service-keys"),
        ("post", "/api/admin/service-keys"),
        ("post", f"/api/admin/service-keys/{created['id']}/revoke"),
    ]:
        res = await getattr(anon_client, method)(
            path, **({"json": {"name": "n", "scopes": ["feedback:full"]}}
                     if method == "post" else {}),
            headers=headers,
        )
        assert res.status_code == 401, (method, path, res.status_code)


@pytest.mark.asyncio
async def test_regular_user_cannot_manage_keys(regular_client):
    res = await regular_client.get("/api/admin/service-keys")
    assert res.status_code == 403


# ── Key auth on the feedback admin API ───────────────────────────────────────

@pytest.mark.asyncio
async def test_key_full_feedback_flow(admin_client, anon_client, db_session, sample_agent):
    ticket_id = await _ticket(anon_client, db_session, sample_agent)
    created = await _mint(admin_client)
    headers = {"x-api-key": created["key"]}

    res = await anon_client.get("/api/admin/feedback/tickets", headers=headers)
    assert res.status_code == 200
    assert any(t["id"] == ticket_id for t in res.json()["tickets"])

    res = await anon_client.get("/api/admin/feedback/unread-count", headers=headers)
    assert res.status_code == 200

    res = await anon_client.get(f"/api/admin/feedback/tickets/{ticket_id}", headers=headers)
    assert res.status_code == 200

    res = await anon_client.post(
        f"/api/admin/feedback/tickets/{ticket_id}/reply",
        headers=headers, json={"body": "On it — fix rolling out."},
    )
    assert res.status_code == 201, res.text
    msg = res.json()
    assert msg["author"] == "admin"
    assert msg["admin_user_id"] is None
    assert msg["meta"] == {"via_api_key": "test-key"}

    res = await anon_client.post(
        f"/api/admin/feedback/tickets/{ticket_id}/status",
        headers=headers, json={"status": "closed"},
    )
    assert res.status_code == 200 and res.json()["status"] == "closed"


@pytest.mark.asyncio
async def test_bearer_form_accepted(admin_client, anon_client):
    created = await _mint(admin_client)
    res = await anon_client.get(
        "/api/admin/feedback/tickets",
        headers={"Authorization": f"Bearer {created['key']}"},
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_bad_revoked_expired_and_wrong_scope_keys(admin_client, anon_client, db_session):
    # Unknown key
    res = await anon_client.get(
        "/api/admin/feedback/tickets", headers={"x-api-key": "lsk_" + "0" * 40}
    )
    assert res.status_code == 401

    # Revoked
    created = await _mint(admin_client)
    await admin_client.post(f"/api/admin/service-keys/{created['id']}/revoke")
    res = await anon_client.get(
        "/api/admin/feedback/tickets", headers={"x-api-key": created["key"]}
    )
    assert res.status_code == 401

    # Expired (row inserted directly — API refuses past expiry)
    secret, key_hash, prefix = generate_key()
    db_session.add(ServiceApiKey(
        id=uuid.uuid4(), name="expired", key_hash=key_hash, key_prefix=prefix,
        scopes=["feedback:full"],
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    ))
    await db_session.commit()
    res = await anon_client.get(
        "/api/admin/feedback/tickets", headers={"x-api-key": secret}
    )
    assert res.status_code == 401

    # Wrong scope
    secret2, key_hash2, prefix2 = generate_key()
    db_session.add(ServiceApiKey(
        id=uuid.uuid4(), name="other-scope", key_hash=key_hash2,
        key_prefix=prefix2, scopes=["errors:full"],
    ))
    await db_session.commit()
    res = await anon_client.get(
        "/api/admin/feedback/tickets", headers={"x-api-key": secret2}
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_bad_key_wins_over_valid_cookie(admin_client):
    """A presented-but-invalid key must not fall back to the cookie session."""
    res = await admin_client.get(
        "/api/admin/feedback/tickets", headers={"x-api-key": "lsk_" + "f" * 40}
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_last_used_stamped(admin_client, anon_client, db_session):
    created = await _mint(admin_client)
    await anon_client.get(
        "/api/admin/feedback/tickets", headers={"x-api-key": created["key"]}
    )
    key = (await db_session.execute(
        select(ServiceApiKey).where(ServiceApiKey.id == uuid.UUID(created["id"]))
    )).scalar_one()
    assert key.last_used_at is not None
