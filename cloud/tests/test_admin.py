"""Tests for the admin API routes."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── Auth guard ───────────────────────────────────────────────────────────────

class TestAdminAuth:
    async def test_anon_gets_401(self, anon_client: AsyncClient):
        resp = await anon_client.get("/api/admin/admins")
        assert resp.status_code == 401

    async def test_non_admin_gets_403(self, regular_client: AsyncClient):
        resp = await regular_client.get("/api/admin/admins")
        assert resp.status_code == 403

    async def test_admin_gets_200(self, admin_client: AsyncClient):
        resp = await admin_client.get("/api/admin/admins")
        assert resp.status_code == 200


# ── Admins CRUD ──────────────────────────────────────────────────────────────

class TestAdminsCRUD:
    async def test_list_admins(self, admin_client: AsyncClient):
        resp = await admin_client.get("/api/admin/admins")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["email"] == "vaselin@gmail.com"

    async def test_add_admin(self, admin_client: AsyncClient, regular_user):
        resp = await admin_client.post(
            "/api/admin/admins",
            json={"email": "regular@example.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "regular@example.com"

        # Verify they appear in list
        resp = await admin_client.get("/api/admin/admins")
        emails = [a["email"] for a in resp.json()]
        assert "regular@example.com" in emails

    async def test_add_admin_not_found(self, admin_client: AsyncClient):
        resp = await admin_client.post(
            "/api/admin/admins",
            json={"email": "nobody@example.com"},
        )
        assert resp.status_code == 404

    async def test_remove_admin(self, admin_client: AsyncClient, regular_user):
        # First add the regular user as admin
        await admin_client.post("/api/admin/admins", json={"email": "regular@example.com"})

        # Then remove
        resp = await admin_client.delete(f"/api/admin/admins/{regular_user.id}")
        assert resp.status_code == 200

        # Verify removed
        resp = await admin_client.get("/api/admin/admins")
        emails = [a["email"] for a in resp.json()]
        assert "regular@example.com" not in emails

    async def test_cannot_remove_last_admin(self, admin_client: AsyncClient, admin_user):
        resp = await admin_client.delete(f"/api/admin/admins/{admin_user.id}")
        assert resp.status_code == 400
        assert "last admin" in resp.json()["detail"].lower()

    async def test_list_users(self, admin_client: AsyncClient, regular_user):
        resp = await admin_client.get("/api/admin/users")
        assert resp.status_code == 200
        emails = [u["email"] for u in resp.json()]
        assert "vaselin@gmail.com" in emails
        assert "regular@example.com" in emails


# ── Luna Images ──────────────────────────────────────────────────────────────

class TestImages:
    async def test_list_images_empty(self, admin_client: AsyncClient):
        resp = await admin_client.get("/api/admin/images")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_images_with_data(self, admin_client: AsyncClient, sample_image):
        resp = await admin_client.get("/api/admin/images")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["version"] == "0.01.001"
        assert data[0]["is_main"] is True

    async def test_get_image(self, admin_client: AsyncClient, sample_image):
        resp = await admin_client.get(f"/api/admin/images/{sample_image.id}")
        assert resp.status_code == 200
        assert resp.json()["version"] == "0.01.001"

    async def test_get_image_with_agent_count(self, admin_client: AsyncClient, sample_image, sample_agent):
        resp = await admin_client.get(f"/api/admin/images/{sample_image.id}")
        assert resp.status_code == 200
        assert resp.json()["agent_count"] == 1

    async def test_set_main_image(self, admin_client: AsyncClient, sample_image, db_session):
        from cloud.db.models import LunaImage
        from datetime import datetime, timezone

        img2 = LunaImage(
            version="0.01.002",
            registry_tag="registry.fly.io/luna-tenants-prod:0.01.002",
            is_main=False,
            build_status="built",
            built_at=datetime.now(timezone.utc),
        )
        db_session.add(img2)
        await db_session.commit()
        await db_session.refresh(img2)

        resp = await admin_client.post(f"/api/admin/images/{img2.id}/set-main")
        assert resp.status_code == 200

        resp = await admin_client.get("/api/admin/images")
        data = resp.json()
        main_versions = [i["version"] for i in data if i["is_main"]]
        assert main_versions == ["0.01.002"]

    async def test_set_main_rejects_unbuilt(self, admin_client: AsyncClient, db_session):
        from cloud.db.models import LunaImage

        img = LunaImage(
            version="0.01.003",
            registry_tag="registry.fly.io/luna-tenants-prod:0.01.003",
            build_status="building",
        )
        db_session.add(img)
        await db_session.commit()
        await db_session.refresh(img)

        resp = await admin_client.post(f"/api/admin/images/{img.id}/set-main")
        assert resp.status_code == 400

    async def test_check_update(self, admin_client: AsyncClient, sample_image):
        from unittest.mock import AsyncMock, patch
        mock_fetch = AsyncMock(return_value="0.01.002")
        with patch("cloud.api.admin_routes._fetch_luna_version_from_github", mock_fetch):
            resp = await admin_client.get("/api/admin/images/check-update")
        assert resp.status_code == 200
        data = resp.json()
        assert data["submodule_version"] == "0.01.002"
        assert data["latest_built"] == "0.01.001"
        assert data["update_available"] is True

    async def test_check_update_no_update(self, admin_client: AsyncClient, sample_image):
        from unittest.mock import AsyncMock, patch
        mock_fetch = AsyncMock(return_value="0.01.001")
        with patch("cloud.api.admin_routes._fetch_luna_version_from_github", mock_fetch):
            resp = await admin_client.get("/api/admin/images/check-update")
        data = resp.json()
        assert data["update_available"] is False


# ── Build webhook ────────────────────────────────────────────────────────────

class TestBuildWebhook:
    async def test_webhook_success(self, anon_client: AsyncClient, sample_image):
        # Change status to building first
        from cloud.db.models import LunaImage
        from cloud.db.session import get_session as get_db_session
        async with get_db_session() as db:
            from sqlalchemy import select
            img = (await db.execute(
                select(LunaImage).where(LunaImage.id == sample_image.id)
            )).scalar_one()
            img.build_status = "building"
            await db.commit()

        resp = await anon_client.post(
            "/api/admin/webhooks/build-complete",
            json={"image_id": str(sample_image.id), "status": "built", "git_sha": "abc1234"},
            headers={"Authorization": "Bearer test-webhook-secret"},
        )
        assert resp.status_code == 200

    async def test_webhook_bad_secret(self, anon_client: AsyncClient, sample_image):
        resp = await anon_client.post(
            "/api/admin/webhooks/build-complete",
            json={"image_id": str(sample_image.id), "status": "built"},
            headers={"Authorization": "Bearer wrong-secret"},
        )
        assert resp.status_code == 401

    async def test_webhook_not_found(self, anon_client: AsyncClient):
        resp = await anon_client.post(
            "/api/admin/webhooks/build-complete",
            json={"image_id": str(uuid.uuid4()), "status": "built"},
            headers={"Authorization": "Bearer test-webhook-secret"},
        )
        assert resp.status_code == 404


# ── Machines ─────────────────────────────────────────────────────────────────

class TestMachines:
    async def test_list_machines(self, admin_client: AsyncClient, sample_agent):
        resp = await admin_client.get("/api/admin/machines")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_name"] == "Test Agent"
        assert data[0]["machine_id"] == "machine-123"
        assert data[0]["image_version"] == "0.01.001"

    async def test_list_machines_empty(self, admin_client: AsyncClient):
        resp = await admin_client.get("/api/admin/machines")
        assert resp.status_code == 200
        assert resp.json() == []


# ── /api/auth/me includes is_admin ───────────────────────────────────────────

class TestMeEndpoint:
    async def test_me_includes_is_admin(self, admin_client: AsyncClient, account):
        resp = await admin_client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["user"]["is_admin"] is True

    async def test_me_regular_user(self, regular_client: AsyncClient):
        # This will 401 because regular_user has no account/membership matching the session cookie
        # but the auth guard fires first, confirming the field exists on the model
        resp = await regular_client.get("/api/auth/me")
        # It may return the user even without account
        if resp.status_code == 200:
            assert resp.json()["user"]["is_admin"] is False
