"""Plan 019 — image-baked plugin set: catalog proxy, selection validation,
image-config honesty, and the build-time resolve endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cloud.api import admin_routes

CHARTS_SHA = "52e063f327a2f1ed505b239344eca9aadb0806fe1921e3f6b58f0f0ba0a9f1b9"
FILES_SHA = "1f38cd1771375b8b9cdde605934b0d8be0ae6c777d3b24db967d2a51412ea293"

FAKE_INDEX = {
    "marketplace": {"id": "x", "name": "Official"},
    "plugins": [
        {"name": "plugin-charts", "version": "0.1.0", "description": "Charts", "sha256": CHARTS_SHA},
        {"name": "plugin-files", "version": "0.2.0", "description": "Files", "sha256": FILES_SHA},
        {"name": "plugin-monday", "version": "0.1.0", "description": "Monday connector", "sha256": "a" * 64},
    ],
}


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        return _FakeResp(FAKE_INDEX)


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    admin_routes._catalog_cache.clear()
    yield
    admin_routes._catalog_cache.clear()


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_bakeable_leaf_vs_connector():
    assert admin_routes._is_bakeable("plugin-charts")
    assert admin_routes._is_bakeable("plugin_web_access")  # underscore-agnostic
    assert not admin_routes._is_bakeable("plugin-monday")
    assert not admin_routes._is_bakeable("plugin-render")
    assert not admin_routes._is_bakeable("plugin-cloudflare")


def test_validate_plugin_set_accepts_leaf():
    out = admin_routes._validate_plugin_set(
        [{"name": "plugin-charts", "version": "0.1.0", "sha256": CHARTS_SHA}]
    )
    assert out == [{"name": "plugin-charts", "version": "0.1.0", "sha256": CHARTS_SHA}]


def test_validate_plugin_set_rejects_connector():
    with pytest.raises(Exception) as ei:
        admin_routes._validate_plugin_set(
            [{"name": "plugin-monday", "version": "0.1.0", "sha256": "a" * 64}]
        )
    assert "not bakeable" in str(ei.value.detail)


def test_validate_plugin_set_rejects_missing_sha():
    with pytest.raises(Exception):
        admin_routes._validate_plugin_set([{"name": "plugin-charts", "version": "0.1.0"}])


def test_validate_plugin_set_rejects_bad_sha():
    with pytest.raises(Exception):
        admin_routes._validate_plugin_set(
            [{"name": "plugin-charts", "version": "0.1.0", "sha256": "nothex"}]
        )


def test_validate_plugin_set_rejects_dupes():
    with pytest.raises(Exception):
        admin_routes._validate_plugin_set([
            {"name": "plugin-charts", "version": "0.1.0", "sha256": CHARTS_SHA},
            {"name": "plugin-charts", "version": "0.1.0", "sha256": CHARTS_SHA},
        ])


# ── catalog proxy ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_catalog_proxy_flags_bakeable(admin_client):
    with patch("cloud.api.admin_routes.httpx.AsyncClient", _FakeClient):
        resp = await admin_client.get("/api/admin/marketplace/catalog")
    assert resp.status_code == 200
    plugins = {p["name"]: p for p in resp.json()["plugins"]}
    assert plugins["plugin-charts"]["bakeable"] is True
    assert plugins["plugin-files"]["bakeable"] is True
    assert plugins["plugin-monday"]["bakeable"] is False
    assert plugins["plugin-charts"]["sha256"] == CHARTS_SHA


@pytest.mark.asyncio
async def test_catalog_proxy_survives_marketplace_down(admin_client):
    class _Boom(_FakeClient):
        async def get(self, url):
            raise RuntimeError("marketplace down")

    with patch("cloud.api.admin_routes.httpx.AsyncClient", _Boom):
        resp = await admin_client.get("/api/admin/marketplace/catalog")
    assert resp.status_code == 200
    assert resp.json()["plugins"] == []


@pytest.mark.asyncio
async def test_catalog_proxy_requires_admin(regular_client):
    resp = await regular_client.get("/api/admin/marketplace/catalog")
    assert resp.status_code in (401, 403)


# ── plugin-meta honesty ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plugin_meta_lists_only_in_tree_core(admin_client):
    """plugin-meta is the hardcoded in-tree core list. Plugins decoupled onto the
    SDK (charts/web-access/files/mcp/recall/funnelfighters) are NOT here — they're
    governed by the Plugin Set picker, not this enable/disable list."""
    resp = await admin_client.get("/api/admin/plugin-meta")
    assert resp.status_code == 200
    by_key = {p["key"]: p for p in resp.json()}
    assert by_key["plugin_vault"]["source"] == "in-tree"
    assert all(p["source"] == "in-tree" for p in resp.json())
    for decoupled in (
        "plugin_charts", "plugin_web_access", "plugin_files",
        "plugin_mcp", "plugin_recall", "plugin_funnelfighters",
    ):
        assert decoupled not in by_key


# ── selection round-trip ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plugin_set_round_trips(admin_client, sample_image):
    iid = str(sample_image.id)
    sel = [{"name": "plugin-charts", "version": "0.1.0", "sha256": CHARTS_SHA}]
    put = await admin_client.put(f"/api/admin/images/{iid}/config", json={"plugin_set": sel})
    assert put.status_code == 200
    assert put.json()["plugin_set"] == sel

    cfg = await admin_client.get(f"/api/admin/images/{iid}/config")
    assert cfg.json()["plugin_set"] == sel


@pytest.mark.asyncio
async def test_plugin_set_save_rejects_connector(admin_client, sample_image):
    iid = str(sample_image.id)
    put = await admin_client.put(
        f"/api/admin/images/{iid}/config",
        json={"plugin_set": [{"name": "plugin-monday", "version": "0.1.0", "sha256": "a" * 64}]},
    )
    assert put.status_code == 400


# ── build-time resolve endpoint ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_endpoint_needs_secret(anon_client, sample_image):
    iid = str(sample_image.id)
    resp = await anon_client.get(f"/api/admin/images/{iid}/plugin-set")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_resolve_returns_selection(admin_client, anon_client, sample_image):
    iid = str(sample_image.id)
    sel = [{"name": "plugin-files", "version": "0.2.0", "sha256": FILES_SHA}]
    await admin_client.put(f"/api/admin/images/{iid}/config", json={"plugin_set": sel})

    resp = await anon_client.get(
        f"/api/admin/images/{iid}/plugin-set",
        headers={"Authorization": "Bearer test-webhook-secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["plugins"] == sel


@pytest.mark.asyncio
async def test_resolve_falls_back_to_seed(anon_client, sample_image):
    """No selection saved → returns the plugin-set.toml seed (3 leaf plugins)."""
    iid = str(sample_image.id)
    resp = await anon_client.get(
        f"/api/admin/images/{iid}/plugin-set",
        headers={"Authorization": "Bearer test-webhook-secret"},
    )
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()["plugins"]}
    assert names == {"plugin-charts", "plugin-web-access", "plugin-files"}
