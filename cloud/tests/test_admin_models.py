"""Plan 018 — admin model-catalog CRUD endpoint tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cloud.db.models import AuditLog, GatewayModel

pytestmark = pytest.mark.asyncio


async def test_models_crud_roundtrip(admin_client, db_session):
    # Empty to start.
    r = await admin_client.get("/api/admin/gateway/models")
    assert r.status_code == 200
    assert r.json() == []

    # Create.
    r = await admin_client.post("/api/admin/gateway/models", json={
        "provider": "openai", "model": "gpt-4.1", "label": "GPT-4.1",
        "kinds": ["reasoning", "summarization"], "aliases": ["gpt41"],
        "context_window": 128000,
    })
    assert r.status_code == 201
    model_id = r.json()["id"]
    assert r.json()["enabled"] is True
    assert r.json()["kinds"] == ["reasoning", "summarization"]

    # Duplicate rejected.
    r = await admin_client.post("/api/admin/gateway/models", json={
        "provider": "openai", "model": "gpt-4.1", "kinds": ["reasoning"],
    })
    assert r.status_code == 409

    # Toggle out, then edit label.
    r = await admin_client.patch(f"/api/admin/gateway/models/{model_id}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = await admin_client.patch(f"/api/admin/gateway/models/{model_id}", json={"label": "GPT 4.1"})
    assert r.status_code == 200
    assert r.json()["label"] == "GPT 4.1"

    # Delete.
    r = await admin_client.delete(f"/api/admin/gateway/models/{model_id}")
    assert r.status_code == 204
    rows = (await db_session.execute(select(GatewayModel))).scalars().all()
    assert rows == []


async def test_invalid_kind_rejected(admin_client):
    r = await admin_client.post("/api/admin/gateway/models", json={
        "provider": "openai", "model": "x", "kinds": ["bogus"],
    })
    assert r.status_code == 400


async def test_recommended_default_is_exclusive_per_kind(admin_client, db_session):
    # Two reasoning models; making the second the default clears the first.
    r1 = await admin_client.post("/api/admin/gateway/models", json={
        "provider": "anthropic", "model": "m1", "kinds": ["reasoning"],
        "recommended_default": True,
    })
    assert r1.status_code == 201
    r2 = await admin_client.post("/api/admin/gateway/models", json={
        "provider": "anthropic", "model": "m2", "kinds": ["reasoning"],
        "recommended_default": True,
    })
    assert r2.status_code == 201

    rows = {m.model: m for m in (await db_session.execute(select(GatewayModel))).scalars().all()}
    assert rows["m1"].recommended_default is False
    assert rows["m2"].recommended_default is True


async def test_models_crud_audited(admin_client, db_session):
    r = await admin_client.post("/api/admin/gateway/models", json={
        "provider": "openai", "model": "gpt-x", "kinds": ["reasoning"],
    })
    assert r.status_code == 201
    actions = {a.action for a in (await db_session.execute(select(AuditLog))).scalars().all()}
    assert "gateway.model.created" in actions


async def test_models_requires_admin(regular_client):
    r = await regular_client.get("/api/admin/gateway/models")
    assert r.status_code in (401, 403)
