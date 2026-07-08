"""Plan 020 — image defaults store, resolver overlay, and catalog search."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cloud.api import admin_routes

CHARTS_SHA = "52e063f327a2f1ed505b239344eca9aadb0806fe1921e3f6b58f0f0ba0a9f1b9"
FILES_SHA = "1f38cd1771375b8b9cdde605934b0d8be0ae6c777d3b24db967d2a51412ea293"

FAKE_INDEX = {
    "plugins": [
        {"name": "plugin-charts", "version": "0.1.0", "description": "Make charts", "sha256": CHARTS_SHA},
        {"name": "plugin-files", "version": "0.2.0", "description": "File ops", "sha256": FILES_SHA},
        {"name": "plugin-monday", "version": "0.1.0", "description": "Monday connector", "sha256": "a" * 64},
    ],
}


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return FAKE_INDEX


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        return _FakeResp()


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    admin_routes._catalog_cache.clear()
    yield
    admin_routes._catalog_cache.clear()


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_validate_default_models_empty_inherits():
    out = admin_routes._validate_default_models({"primary": {}, "fast": None})
    assert out == {"primary": {}, "fast": {}}


def test_validate_default_models_pins_both_fields():
    out = admin_routes._validate_default_models(
        {"primary": {"provider": "anthropic", "model": "claude-x"}}
    )
    assert out["primary"] == {"provider": "anthropic", "model": "claude-x"}


def test_validate_default_models_rejects_partial():
    with pytest.raises(Exception):
        admin_routes._validate_default_models({"primary": {"provider": "anthropic"}})


def test_overlay_merges_one_level():
    base = {"models": {"primary": {}, "fast": {}}, "plugin_set": []}
    out = admin_routes._overlay(base, {"models": {"primary": {"provider": "p", "model": "m"}}})
    assert out["models"]["primary"] == {"provider": "p", "model": "m"}
    assert out["models"]["fast"] == {}  # untouched key preserved


# ── machine params (Plan 036) ─────────────────────────────────────────────────

def test_validate_machine_accepts_valid():
    out = admin_routes._validate_machine(
        {"cpu_kind": "performance", "cpus": 2, "memory_mb": 4096, "region": "iad"}
    )
    assert out == {"cpu_kind": "performance", "cpus": 2, "memory_mb": 4096, "region": "iad"}


def test_validate_machine_fills_defaults():
    out = admin_routes._validate_machine({"region": "lhr"})
    assert out == {"cpu_kind": "shared", "cpus": 1, "memory_mb": 1024, "region": "lhr"}


@pytest.mark.parametrize("bad", [
    {"cpu_kind": "turbo"},                                  # unknown kind
    {"cpus": 3},                                            # not a valid count
    {"memory_mb": 300},                                     # not a known option
    {"cpu_kind": "performance", "cpus": 1, "memory_mb": 256},  # below per-CPU floor
    {"cpu_kind": "shared", "cpus": 1, "memory_mb": 4096},   # above per-CPU ceiling
    {"region": "mars"},                                     # unknown region
])
def test_validate_machine_rejects(bad):
    with pytest.raises(Exception):
        admin_routes._validate_machine(bad)


# ── endpoints ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_defaults_requires_admin(regular_client):
    resp = await regular_client.get("/api/admin/defaults")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_defaults_round_trip(admin_client):
    body = {
        "models": {"primary": {"provider": "anthropic", "model": "claude-test"}, "fast": {}},
        "plugin_set": [{"name": "plugin-charts", "version": "0.1.0", "sha256": CHARTS_SHA}],
    }
    put = await admin_client.put("/api/admin/defaults", json=body)
    assert put.status_code == 200
    assert put.json()["models"]["primary"] == {"provider": "anthropic", "model": "claude-test"}
    assert put.json()["plugin_set"] == body["plugin_set"]

    got = await admin_client.get("/api/admin/defaults")
    assert got.json()["models"]["primary"] == {"provider": "anthropic", "model": "claude-test"}
    assert got.json()["plugin_set"] == body["plugin_set"]


@pytest.mark.asyncio
async def test_defaults_machine_round_trip(admin_client):
    body = {"machine": {"cpu_kind": "performance", "cpus": 2, "memory_mb": 8192, "region": "iad"}}
    put = await admin_client.put("/api/admin/defaults", json=body)
    assert put.status_code == 200
    assert put.json()["machine"] == body["machine"]

    got = await admin_client.get("/api/admin/defaults")
    assert got.json()["machine"] == body["machine"]


@pytest.mark.asyncio
async def test_defaults_rejects_invalid_machine(admin_client):
    resp = await admin_client.put(
        "/api/admin/defaults",
        json={"machine": {"cpu_kind": "shared", "cpus": 1, "memory_mb": 65536, "region": "sjc"}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_defaults_rejects_connector_in_set(admin_client):
    resp = await admin_client.put(
        "/api/admin/defaults",
        json={"plugin_set": [{"name": "plugin-monday", "version": "0.1.0", "sha256": "a" * 64}]},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_stored_defaults_overlay_image_config(admin_client, sample_image):
    """An image with no explicit override inherits the stored defaults."""
    await admin_client.put(
        "/api/admin/defaults",
        json={"plugin_set": [{"name": "plugin-files", "version": "0.2.0", "sha256": FILES_SHA}]},
    )
    cfg = await admin_client.get(f"/api/admin/images/{sample_image.id}/config")
    assert cfg.status_code == 200
    assert cfg.json()["plugin_set"] == [
        {"name": "plugin-files", "version": "0.2.0", "sha256": FILES_SHA}
    ]


@pytest.mark.asyncio
async def test_catalog_search_filters(admin_client):
    with patch("cloud.api.admin_routes.httpx.AsyncClient", _FakeClient):
        resp = await admin_client.get("/api/admin/marketplace/catalog", params={"q": "chart"})
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()["plugins"]}
    assert names == {"plugin-charts"}


@pytest.mark.asyncio
async def test_catalog_search_matches_description(admin_client):
    with patch("cloud.api.admin_routes.httpx.AsyncClient", _FakeClient):
        resp = await admin_client.get("/api/admin/marketplace/catalog", params={"q": "connector"})
    names = {p["name"] for p in resp.json()["plugins"]}
    assert names == {"plugin-monday"}
