"""Plan 026.1 — discovery endpoint, guardrails, query-auth proxy."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from cloud.db.models import GatewayKey, GatewayService, PluginCatalogEntry, UsageEvent
from cloud.gateway.crypto import encrypt_key
from cloud.gateway.registry import default_names
from cloud.gateway.tokens import issue_token

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_policy_cache():
    from cloud.gateway.policy import invalidate_policy_cache
    invalidate_policy_cache()
    yield
    invalidate_policy_cache()


async def _svc(db, slug, **over):
    fields = {
        "slug": slug, "display_name": slug, "upstream_url": "http://upstream.test",
        "auth_style": "header:x-api-key", **default_names(slug), **over,
    }
    db.add(GatewayService(**fields))
    await db.flush()


async def _key(db, slug, value="real-key"):
    db.add(GatewayKey(service_slug=slug, scope="global", priority=1,
                      api_key_enc=encrypt_key(value), label="", is_active=True))
    await db.flush()


async def _binding(db, plugin, slug, *, tier="default", category=None):
    db.add(PluginCatalogEntry(plugin_name=plugin, display_name=plugin, tier=tier,
                              service_slug=slug, key_mode="proxy", enabled=True, category=category))
    await db.flush()


# ── Discovery ────────────────────────────────────────────────────────────────

async def test_discovery_provisioned_vs_available(anon_client, db_session, sample_agent, sample_image):
    await _svc(db_session, "browser-use", auth_style="header:X-Browser-Use-API-Key", provision_by_default=True)
    await _key(db_session, "browser-use", value="bu-real")
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await _key(db_session, "monday", value="m-real")
    await _binding(db_session, "plugin-browser", "browser-use", category="Browser automation")
    await _binding(db_session, "plugin-monday", "monday", tier="supported", category="Project mgmt")
    # Agent runs plugin-browser (opt-in), not plugin-monday.
    sample_agent.config_overrides = {"installed_plugins": ["plugin-browser"]}
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    r = await anon_client.get("/api/agent/gateway/services",
                              headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = {s["slug"]: s for s in r.json()}

    assert body["browser-use"]["provisioned"] is True
    assert body["browser-use"]["has_key"] is True
    assert body["browser-use"]["status"] == "active"
    assert body["browser-use"]["proxy_url"].endswith("/proxy/browser-use")

    assert body["monday"]["provisioned"] is False
    assert body["monday"]["has_key"] is True
    assert body["monday"]["status"] == "available"

    # No secrets anywhere
    assert "bu-real" not in r.text and "m-real" not in r.text and token not in r.text


async def test_discovery_bad_tokens_401(anon_client, db_session, sample_agent, sample_image):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    assert (await anon_client.get("/api/agent/gateway/services")).status_code == 401
    r = await anon_client.get("/api/agent/gateway/services",
                              headers={"Authorization": "Bearer lsv1-garbage"})
    assert r.status_code == 401

    # Revoked: issuing a new token revokes the old one.
    await issue_token(db_session, sample_agent.id)
    await db_session.commit()
    r = await anon_client.get("/api/agent/gateway/services",
                              headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


# ── Connect (bind endpoint) ──────────────────────────────────────────────────

async def test_connect_promotes_available_to_provisioned(anon_client, db_session, sample_agent, sample_image):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await _key(db_session, "monday", value="m-real")
    # Cataloged (so it's advertised) but the agent doesn't run plugin-monday.
    await _binding(db_session, "plugin-monday", "monday", tier="supported")
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    # Before: available (has a key, not provisioned for this agent).
    r = await anon_client.get("/api/agent/gateway/services",
                              headers={"Authorization": f"Bearer {token}"})
    body = {s["slug"]: s for s in r.json()}
    assert body["monday"]["provisioned"] is False
    assert body["monday"]["status"] == "available"

    # Connect.
    r = await anon_client.post("/api/agent/gateway/connect", json={"slug": "monday"},
                               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    out = r.json()
    assert out["connected"] is True and out["provisioned"] is True
    assert out["status"] == "active" and out["display_name"] == "monday"
    assert "m-real" not in r.text and token not in r.text

    # After: provisioned + active in discovery.
    r = await anon_client.get("/api/agent/gateway/services",
                              headers={"Authorization": f"Bearer {token}"})
    body = {s["slug"]: s for s in r.json()}
    assert body["monday"]["provisioned"] is True
    assert body["monday"]["status"] == "active"

    # Persisted on the agent.
    await db_session.refresh(sample_agent)
    assert "monday" in (sample_agent.config_overrides or {}).get("connected_services", [])


async def test_connect_without_key_is_provisioned_but_inactive(anon_client, db_session, sample_agent, sample_image):
    await _svc(db_session, "monday", auth_style="header:Authorization")  # no key in pool
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    r = await anon_client.post("/api/agent/gateway/connect", json={"slug": "monday"},
                               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    out = r.json()
    assert out["provisioned"] is True
    assert out["connected"] is False and out["has_key"] is False
    assert out["status"] == "available"


async def test_connect_idempotent(anon_client, db_session, sample_agent, sample_image):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await _key(db_session, "monday", value="m-real")
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    for _ in range(3):
        r = await anon_client.post("/api/agent/gateway/connect", json={"slug": "monday"},
                                   headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    await db_session.refresh(sample_agent)
    assert (sample_agent.config_overrides or {}).get("connected_services") == ["monday"]


async def test_connect_unknown_service_404(anon_client, db_session, sample_agent):
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()
    r = await anon_client.post("/api/agent/gateway/connect", json={"slug": "nope"},
                               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


async def test_connect_disabled_service_404(anon_client, db_session, sample_agent):
    await _svc(db_session, "monday", auth_style="header:Authorization", enabled=False)
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()
    r = await anon_client.post("/api/agent/gateway/connect", json={"slug": "monday"},
                               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


async def test_connect_denied_by_policy_403(anon_client, db_session, sample_agent):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await _key(db_session, "monday", value="m-real")
    sample_agent.config_overrides = {"gateway": {"deny": ["monday"]}}
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()
    r = await anon_client.post("/api/agent/gateway/connect", json={"slug": "monday"},
                               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


async def test_connect_bad_token_401(anon_client, db_session, sample_agent):
    await _svc(db_session, "monday", auth_style="header:Authorization")
    await db_session.commit()
    assert (await anon_client.post("/api/agent/gateway/connect", json={"slug": "monday"})).status_code == 401
    r = await anon_client.post("/api/agent/gateway/connect", json={"slug": "monday"},
                               headers={"Authorization": "Bearer lsv1-garbage"})
    assert r.status_code == 401


# ── Guardrails ───────────────────────────────────────────────────────────────

@pytest.fixture
def upstream(monkeypatch):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url)})
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("cloud.api.gateway_proxy._get_client", lambda: client)
    return calls


async def test_proxy_deny_blocks_and_attributes(anon_client, db_session, sample_agent, upstream):
    await _svc(db_session, "browser-use", auth_style="header:X-Browser-Use-API-Key")
    await _key(db_session, "browser-use", value="bu-real")
    sample_agent.config_overrides = {"gateway": {"deny": ["browser-use"]}}
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    r = await anon_client.get("/proxy/browser-use/v3/me",
                              headers={"X-Browser-Use-API-Key": token})
    assert r.status_code == 403
    assert upstream == []  # never reached the provider

    events = (await db_session.execute(select(UsageEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].billable is False and events[0].status_code == 403


# ── Query-auth proxy ─────────────────────────────────────────────────────────

async def test_query_auth_swaps_token_for_real_key(anon_client, db_session, sample_agent):
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    import cloud.api.gateway_proxy as gp
    gp._client = client  # force our mock client

    await _svc(db_session, "giphy", upstream_url="https://api.giphy.com/v1", auth_style="query:api_key")
    await _key(db_session, "giphy", value="giphy-real")
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    try:
        r = await anon_client.get(f"/proxy/giphy/gifs/search?api_key={token}&q=cat")
    finally:
        gp._client = None

    assert r.status_code == 200
    url = captured[0]
    assert "api_key=giphy-real" in url
    assert "q=cat" in url
    assert token not in url
