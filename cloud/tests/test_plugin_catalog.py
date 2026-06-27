"""Plan 026 — plugin catalog: suggester, CRUD, membership-driven provisioning."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from cloud.db.models import GatewayKey, GatewayService, PluginCatalogEntry
from cloud.gateway.crypto import encrypt_key
from cloud.gateway.provision_env import build_gateway_env
from cloud.gateway.registry import default_names, parse_auth_style, suggest_service
from cloud.gateway.tokens import verify_token

pytestmark = pytest.mark.asyncio


async def _svc(db, slug, **over):
    fields = {
        "slug": slug, "display_name": slug, "upstream_url": "http://upstream.test",
        "auth_style": "header:x-api-key", **default_names(slug), **over,
    }
    db.add(GatewayService(**fields))
    await db.flush()


async def _key(db, slug, value="real-key", **over):
    db.add(GatewayKey(service_slug=slug, scope="global", priority=over.pop("priority", 1),
                      api_key_enc=encrypt_key(value), label="", is_active=True, **over))
    await db.flush()


async def _binding(db, plugin, slug, *, key_mode="proxy", tier="default"):
    db.add(PluginCatalogEntry(plugin_name=plugin, display_name=plugin, tier=tier,
                              service_slug=slug, key_mode=key_mode, enabled=True))
    await db.flush()


# ── Suggester + auth style ───────────────────────────────────────────────────

async def test_suggest_known():
    s = suggest_service("plugin-monday")
    assert s["slug"] == "monday"
    assert s["upstream_url"] == "https://api.monday.com/v2"
    assert s["auth_style"] == "header:Authorization"
    assert s["needs_review"] is False


async def test_suggest_unknown_flags_review():
    s = suggest_service("plugin-totally-made-up")
    assert s["slug"] == "totally-made-up"
    assert s["upstream_url"] == ""
    assert s["needs_review"] is True


async def test_parse_query_auth_style():
    a = parse_auth_style("query:api_key")
    assert a.is_query and a.header == "api_key" and a.scheme is None


# ── Membership-driven provisioning ───────────────────────────────────────────

async def test_proxy_binding_provisions_when_keyed(db_session, sample_agent):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await _key(db_session, "monday")
    await _binding(db_session, "plugin-monday", "monday", tier="supported")
    await db_session.commit()

    env = await build_gateway_env(
        db_session, sample_agent.id,
        image_config={"plugin_set": [{"name": "plugin-monday", "version": "1", "sha256": "x"}]},
    )
    await db_session.commit()

    assert env["LUNA_MONDAY_BASE_URL"].endswith("/proxy/monday")
    assert env["LUNA_MONDAY_API_KEY"].startswith("lsv1-")
    assert env["LUNA_GATEWAY_URL"].endswith("/proxy")
    assert env["LUNA_GATEWAY_TOKEN"].startswith("lsv1-")
    assert "real-key" not in json.dumps(env)
    assert await verify_token(db_session, env["LUNA_GATEWAY_TOKEN"]) == sample_agent.id


async def test_proxy_binding_key_gated_skips_when_no_key(db_session, sample_agent):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await _binding(db_session, "plugin-monday", "monday")
    await db_session.commit()

    env = await build_gateway_env(
        db_session, sample_agent.id,
        image_config={"plugin_set": [{"name": "plugin-monday", "version": "1", "sha256": "x"}]},
    )
    await db_session.commit()
    assert "LUNA_MONDAY_BASE_URL" not in env
    assert env["LUNA_GATEWAY_URL"].endswith("/proxy")  # pair still emitted


async def test_installed_optin_plugin_provisions(db_session, sample_agent):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await _key(db_session, "monday")
    await _binding(db_session, "plugin-monday", "monday", tier="supported")
    await db_session.commit()

    # Not in plugin_set; opt-in installed via config_overrides.
    env = await build_gateway_env(
        db_session, sample_agent.id, image_config={},
        agent_overrides={"installed_plugins": ["plugin-monday"]},
    )
    await db_session.commit()
    assert env["LUNA_MONDAY_BASE_URL"].endswith("/proxy/monday")


async def test_env_mode_injects_real_key(db_session, sample_agent):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await _key(db_session, "monday", value="real-monday")
    await _binding(db_session, "plugin-monday", "monday", key_mode="env")
    await db_session.commit()

    env = await build_gateway_env(
        db_session, sample_agent.id,
        image_config={"plugin_set": [{"name": "plugin-monday", "version": "1", "sha256": "x"}]},
    )
    await db_session.commit()
    assert env["LUNA_MONDAY_API_KEY"] == "real-monday"   # real key on machine (opt-in)
    assert "LUNA_MONDAY_BASE_URL" not in env             # direct upstream, no proxy


# ── Admin CRUD ───────────────────────────────────────────────────────────────

async def test_catalog_crud(admin_client, db_session):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await db_session.commit()

    # suggest endpoint
    r = await admin_client.get("/api/admin/plugin-catalog/suggest", params={"plugin_name": "plugin-monday"})
    assert r.status_code == 200 and r.json()["upstream_url"] == "https://api.monday.com/v2"

    # create
    r = await admin_client.post("/api/admin/plugin-catalog", json={
        "plugin_name": "plugin-monday", "tier": "supported",
        "service_slug": "monday", "key_mode": "proxy",
    })
    assert r.status_code == 201
    assert r.json()["service_slug"] == "monday"

    # list (filtered)
    r = await admin_client.get("/api/admin/plugin-catalog", params={"tier": "supported"})
    assert r.status_code == 200 and [e["plugin_name"] for e in r.json()] == ["plugin-monday"]

    # patch
    r = await admin_client.patch("/api/admin/plugin-catalog/plugin-monday", json={"key_mode": "env"})
    assert r.status_code == 200 and r.json()["key_mode"] == "env"

    # delete
    r = await admin_client.delete("/api/admin/plugin-catalog/plugin-monday")
    assert r.status_code == 204
    assert (await db_session.execute(select(PluginCatalogEntry))).scalars().first() is None


async def test_catalog_requires_admin(regular_client):
    r = await regular_client.get("/api/admin/plugin-catalog")
    assert r.status_code in (401, 403)
