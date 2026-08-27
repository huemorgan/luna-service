"""Plan 076 phase 3 — admin webhook endpoints."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cloud.db.models import RelayDelivery, WebhookEndpoint
from cloud.tests.test_webhooks import _mint


@pytest.mark.asyncio
class TestAdminEndpoints:
    async def test_requires_admin(self, regular_client):
        res = await regular_client.get("/api/admin/webhooks/endpoints")
        assert res.status_code in (401, 403)

    async def test_list_with_agent_join(self, admin_client, db_session, sample_agent):
        await _mint(admin_client, db_session, sample_agent)
        res = await admin_client.get("/api/admin/webhooks/endpoints")
        assert res.status_code == 200
        rows = res.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["agent_slug"] == sample_agent.slug
        assert row["agent_name"] == sample_agent.name
        assert row["plugin"] == "plugin-webhooks"
        assert "secret" not in row
        assert row["public_url"].endswith(row["hook_slug"])

    async def test_agent_slug_filter(self, admin_client, db_session, sample_agent):
        await _mint(admin_client, db_session, sample_agent)
        res = await admin_client.get("/api/admin/webhooks/endpoints?agent_slug=nope")
        assert res.json() == []
        res = await admin_client.get(
            f"/api/admin/webhooks/endpoints?agent_slug={sample_agent.slug}"
        )
        assert len(res.json()) == 1

    async def test_deliveries_only_generic_hooks(self, admin_client, db_session, sample_agent):
        db_session.add(RelayDelivery(
            webhook_id="composio-trigger-1", agent_id=sample_agent.id,
            status="pending", body="{}",
        ))
        db_session.add(RelayDelivery(
            webhook_id="hook_abc123", agent_id=sample_agent.id,
            status="pending", body="{}", target_path="/api/p/x/hooks/in",
        ))
        await db_session.commit()
        res = await admin_client.get("/api/admin/webhooks/deliveries")
        rows = res.json()
        assert [r["webhook_id"] for r in rows] == ["hook_abc123"]
        assert rows[0]["target_path"] == "/api/p/x/hooks/in"
        assert rows[0]["agent_slug"] == sample_agent.slug

    async def test_patch_and_delete(self, admin_client, db_session, sample_agent):
        await _mint(admin_client, db_session, sample_agent)
        ep_id = (await admin_client.get("/api/admin/webhooks/endpoints")).json()[0]["id"]

        res = await admin_client.patch(
            f"/api/admin/webhooks/endpoints/{ep_id}", json={"enabled": False})
        assert res.json()["enabled"] is False

        res = await admin_client.delete(f"/api/admin/webhooks/endpoints/{ep_id}")
        assert res.json()["ok"] is True
        db_session.expire_all()
        left = (await db_session.execute(select(WebhookEndpoint))).scalars().all()
        assert left == []

    async def test_patch_unknown_404(self, admin_client):
        res = await admin_client.patch(
            "/api/admin/webhooks/endpoints/not-a-uuid", json={"enabled": True})
        assert res.status_code == 404
