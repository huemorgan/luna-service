"""Build experimental Luna branches: branch listing + branch-qualified builds."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cloud.api import admin_routes


# ── pure helper ───────────────────────────────────────────────────────────────

def test_slugify_branch():
    assert admin_routes._slugify_branch("8.5-pluginsdk") == "8.5-pluginsdk"
    assert admin_routes._slugify_branch("feature/foo bar") == "feature-foo-bar"
    assert admin_routes._slugify_branch("---") == "branch"


# ── branches endpoint ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_branches_endpoint(admin_client):
    fake = [
        {"name": "main", "commit_sha": "a", "merged": True, "ahead_by": 0, "behind_by": 0},
        {"name": "8.5-pluginsdk", "commit_sha": "b", "merged": False, "ahead_by": 12, "behind_by": 3},
    ]
    with patch("cloud.api.admin_routes._list_luna_branches", AsyncMock(return_value=fake)):
        resp = await admin_client.get("/api/admin/luna/branches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo"] == admin_routes.LUNA_GITHUB_REPO
    names = [b["name"] for b in body["branches"]]
    assert "8.5-pluginsdk" in names


@pytest.mark.asyncio
async def test_branches_endpoint_requires_admin(regular_client):
    resp = await regular_client.get("/api/admin/luna/branches")
    assert resp.status_code in (401, 403)


# ── build from branch ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_main_unchanged(admin_client):
    with patch(
        "cloud.api.admin_routes._fetch_luna_version_from_github",
        AsyncMock(return_value=("0.99.0", "github")),
    ):
        resp = await admin_client.post("/api/admin/images/build?branch=main")
    assert resp.status_code == 200
    img = resp.json()
    assert img["version"] == "0.99.0"
    assert img["git_branch"] == "main"


@pytest.mark.asyncio
async def test_build_branch_qualifies_version(admin_client):
    sha = "abcdef1234567890"
    with patch(
        "cloud.api.admin_routes._fetch_luna_ref_info",
        AsyncMock(return_value=("0.13.015", sha)),
    ):
        resp = await admin_client.post("/api/admin/images/build?branch=8.5-pluginsdk")
    assert resp.status_code == 200
    img = resp.json()
    assert img["version"] == "0.13.015-8.5-pluginsdk-abcdef1"
    assert img["git_branch"] == "8.5-pluginsdk"
    assert img["git_sha"] == sha
    assert img["registry_tag"].endswith(":0.13.015-8.5-pluginsdk-abcdef1")


@pytest.mark.asyncio
async def test_build_branch_not_found(admin_client):
    with patch(
        "cloud.api.admin_routes._fetch_luna_ref_info",
        AsyncMock(return_value=(None, None)),
    ):
        resp = await admin_client.post("/api/admin/images/build?branch=does-not-exist")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_build_branch_no_version_in_init(admin_client):
    with patch(
        "cloud.api.admin_routes._fetch_luna_ref_info",
        AsyncMock(return_value=(None, "deadbeef00")),
    ):
        resp = await admin_client.post("/api/admin/images/build?branch=weird")
    assert resp.status_code == 400
