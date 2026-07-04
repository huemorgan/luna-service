"""Plan 034 — WhatsApp gateway monitoring routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cloud.api.whatsapp_routes as wa
from cloud import config

GATEWAY_STATS = {
    "status": "open",
    "connected": True,
    "self_jid": "972500000000@s.whatsapp.net",
    "has_qr": False,
    "uptime_s": 3600,
    "sent_today": 12,
    "send_daily_cap": 300,
    "db": {"ok": True, "latency_ms": 9},
    "totals": {"messages": 100, "chats": 5, "users": 4},
    "last_hour": {"messages_in": 1, "messages_out": 1, "active_chats": 1, "active_users": 1},
    "last_24h": {"messages_in": 10, "messages_out": 8, "active_chats": 3, "active_users": 3},
    "media_24h": {},
    "hourly": [],
    "last_message_at": None,
}


def _settings():
    """The settings object the route actually sees (conftest patches
    cloud.config.get_settings; mutate its return value, not our import)."""
    return config.get_settings()


@pytest.fixture(autouse=True)
def _reset_cache_and_config(monkeypatch):
    wa._stats_cache = None
    s = _settings()
    monkeypatch.setattr(s, "whatsapp_gateway_url", "https://wa.example.com", raising=False)
    monkeypatch.setattr(s, "whatsapp_gateway_admin_key", "test-key", raising=False)
    yield
    wa._stats_cache = None


def _mock_gateway(status_code=200, json_body=None, exc=None):
    """Patch httpx.AsyncClient used by the routes module."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else GATEWAY_STATS
    resp.text = "<html>qr</html>"
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if exc:
        client.get = AsyncMock(side_effect=exc)
    else:
        client.get = AsyncMock(return_value=resp)
    return patch.object(wa.httpx, "AsyncClient", return_value=client), client


# ── auth ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_requires_admin(regular_client):
    assert (await regular_client.get("/api/admin/whatsapp/stats")).status_code == 403


@pytest.mark.asyncio
async def test_stats_requires_auth(anon_client):
    assert (await anon_client.get("/api/admin/whatsapp/stats")).status_code == 401


# ── config states ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unconfigured(admin_client, monkeypatch):
    monkeypatch.setattr(_settings(), "whatsapp_gateway_url", "", raising=False)
    res = await admin_client.get("/api/admin/whatsapp/stats")
    assert res.status_code == 200
    assert res.json() == {"configured": False}


# ── proxy behavior ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_ok(admin_client):
    patcher, client = _mock_gateway()
    with patcher:
        res = await admin_client.get("/api/admin/whatsapp/stats")
    body = res.json()
    assert res.status_code == 200
    assert body["configured"] and body["reachable"] and body["authorized"]
    assert body["stats"]["connected"] is True
    assert body["qr_url"] is None  # has_qr false
    # admin key sent upstream as header, never echoed back
    _, kwargs = client.get.call_args
    assert kwargs["headers"]["x-admin-key"] == "test-key"
    assert "test-key" not in res.text


@pytest.mark.asyncio
async def test_stats_qr_url_when_relink_needed(admin_client):
    patcher, _ = _mock_gateway(json_body={**GATEWAY_STATS, "has_qr": True, "connected": False, "status": "linking"})
    with patcher:
        body = (await admin_client.get("/api/admin/whatsapp/stats")).json()
    assert body["qr_url"] == "/api/admin/whatsapp/qr"


@pytest.mark.asyncio
async def test_stats_unauthorized_upstream(admin_client):
    patcher, _ = _mock_gateway(status_code=401)
    with patcher:
        body = (await admin_client.get("/api/admin/whatsapp/stats")).json()
    assert body == {"configured": True, "reachable": True, "authorized": False, "qr_url": None}


@pytest.mark.asyncio
async def test_stats_unreachable_is_200(admin_client):
    patcher, _ = _mock_gateway(exc=wa.httpx.ConnectError("boom"))
    with patcher:
        res = await admin_client.get("/api/admin/whatsapp/stats")
    assert res.status_code == 200
    assert res.json() == {"configured": True, "reachable": False, "qr_url": None}


@pytest.mark.asyncio
async def test_stats_cached_within_ttl(admin_client):
    patcher, client = _mock_gateway()
    with patcher:
        await admin_client.get("/api/admin/whatsapp/stats")
        await admin_client.get("/api/admin/whatsapp/stats")
        await admin_client.get("/api/admin/whatsapp/stats")
    assert client.get.call_count == 1


# ── QR proxy ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_qr_proxied_server_side(admin_client):
    patcher, client = _mock_gateway()
    with patcher:
        res = await admin_client.get("/api/admin/whatsapp/qr")
    assert res.status_code == 200
    assert "qr" in res.text
    _, kwargs = client.get.call_args
    assert kwargs["params"]["key"] == "test-key"


@pytest.mark.asyncio
async def test_qr_requires_admin(regular_client):
    assert (await regular_client.get("/api/admin/whatsapp/qr")).status_code == 403


# ── instances ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_instances_reports_plugin_membership(admin_client, db_session, sample_agent):
    sample_agent.config_overrides = {"installed_plugins": ["plugin-whatsapp"]}
    db_session.add(sample_agent)
    await db_session.commit()

    res = await admin_client.get("/api/admin/whatsapp/instances")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["slug"] == "test-account-test-agent"
    assert rows[0]["plugin_installed"] is True


@pytest.mark.asyncio
async def test_instances_without_plugin(admin_client, sample_agent):
    rows = (await admin_client.get("/api/admin/whatsapp/instances")).json()
    assert rows[0]["plugin_installed"] is False
