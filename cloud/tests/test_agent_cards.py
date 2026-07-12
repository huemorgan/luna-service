"""Plan 038 — agent card colors: PATCH validation, palette fallback, random pick on create."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cloud.api.agent_routes import AGENT_COLOR_PALETTE, _fallback_color

AGENT_ID = "00000000-0000-0000-0000-000000000020"


@pytest.mark.asyncio
async def test_patch_color(admin_client, sample_agent):
    resp = await admin_client.patch(f"/api/agents/{AGENT_ID}", json={"color": "#0EA5E9"})
    assert resp.status_code == 200
    assert resp.json()["color"] == "#0ea5e9"  # stored lowercased
    assert resp.json()["name"] == "Test Agent"  # name untouched


@pytest.mark.asyncio
async def test_patch_color_invalid_hex(admin_client, sample_agent):
    for bad in ("red", "#fff", "#12345g", "0ea5e9", "#0ea5e9ff"):
        resp = await admin_client.patch(f"/api/agents/{AGENT_ID}", json={"color": bad})
        assert resp.status_code == 400, bad


@pytest.mark.asyncio
async def test_patch_nothing_to_update(admin_client, sample_agent):
    resp = await admin_client.patch(f"/api/agents/{AGENT_ID}", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_name_only_still_works(admin_client, sample_agent):
    resp = await admin_client.patch(f"/api/agents/{AGENT_ID}", json={"name": "Renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_null_color_falls_back_to_palette(admin_client, sample_agent):
    assert sample_agent.color is None
    resp = await admin_client.get("/api/agents")
    assert resp.status_code == 200
    color = resp.json()[0]["color"]
    assert color in AGENT_COLOR_PALETTE
    assert color == _fallback_color(sample_agent.id)  # deterministic


@pytest.mark.asyncio
async def test_create_agent_gets_palette_color(admin_client, account):
    with patch(
        "cloud.provisioning.workflow.provision_luna_for_account",
        new=AsyncMock(return_value=None),
    ):
        resp = await admin_client.post("/api/agents", json={"name": "Colorful"})
    assert resp.status_code == 201
    assert resp.json()["color"] in AGENT_COLOR_PALETTE
