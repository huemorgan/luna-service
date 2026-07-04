"""Plan 034/034.1 — instances join + public inbound relay."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cloud.api.whatsapp_routes as wa
import cloud.whatsapp.provision as prov
from cloud import config

ACCOUNTS_STATS = {
    "status": "open", "connected": True, "self_jid": None, "has_qr": False,
    "accounts": [
        {"account_id": "test-account-test-agent", "status": "linking", "connected": False,
         "has_qr": True, "self_jid": None, "messages_24h_in": 3, "messages_24h_out": 2,
         "sent_today": 1, "daily_cap": 300},
        {"account_id": "default", "status": "open", "connected": True,
         "has_qr": False, "self_jid": "9725@s.whatsapp.net"},
    ],
}


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    wa._stats_cache = None
    s = config.get_settings()
    monkeypatch.setattr(s, "whatsapp_gateway_url", "https://wa.example.com", raising=False)
    monkeypatch.setattr(s, "whatsapp_gateway_admin_key", "test-key", raising=False)
    monkeypatch.setattr(s, "base_url", "https://luna.test", raising=False)
    yield
    wa._stats_cache = None


def _gw_response(status_code=201, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = "gw"
    return resp


# ── instances join ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_instances_joins_gateway_accounts(admin_client, sample_agent):
    with patch.object(wa, "_fetch_stats", AsyncMock(return_value={
        "configured": True, "reachable": True, "authorized": True, "stats": ACCOUNTS_STATS,
    })):
        rows = (await admin_client.get("/api/admin/whatsapp/instances")).json()
    row = next(r for r in rows if r["slug"] == sample_agent.slug)
    assert row["account"]["status"] == "linking"
    assert row["account"]["has_qr"] is True
    assert row["account"]["messages_24h_in"] == 3


@pytest.mark.asyncio
async def test_instances_no_account(admin_client, sample_agent):
    with patch.object(wa, "_fetch_stats", AsyncMock(return_value={
        "configured": True, "reachable": True, "authorized": True,
        "stats": {**ACCOUNTS_STATS, "accounts": []},
    })):
        rows = (await admin_client.get("/api/admin/whatsapp/instances")).json()
    assert rows[0]["account"] is None


# ── inbound relay ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_relay_forwards_raw_body_and_hmac_headers(anon_client, sample_agent):
    upstream = MagicMock(status_code=200, content=b'{"answered":true}',
                         headers={"content-type": "application/json"})
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=upstream)

    with patch.object(wa.httpx, "AsyncClient", return_value=client):
        res = await anon_client.post(
            f"/api/webhooks/whatsapp/{sample_agent.slug}/inbound",
            content=b'{"text":"hi"}',
            headers={"x-wa-timestamp": "123", "x-wa-signature": "abc",
                     "content-type": "application/json"},
        )

    assert res.status_code == 200 and res.json() == {"answered": True}
    args, kwargs = client.post.call_args
    assert args[0].endswith("/api/p/plugin-whatsapp/inbound")
    assert kwargs["content"] == b'{"text":"hi"}'
    assert kwargs["headers"]["x-wa-timestamp"] == "123"
    assert kwargs["headers"]["x-wa-signature"] == "abc"
    assert kwargs["headers"]["fly-force-instance-id"] == sample_agent.runtime_ref
    assert "x-luna-proxy-secret" in kwargs["headers"]


@pytest.mark.asyncio
async def test_relay_unknown_slug_404(anon_client):
    res = await anon_client.post("/api/webhooks/whatsapp/nope/inbound", content=b"{}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_relay_passes_through_plugin_401(anon_client, sample_agent):
    upstream = MagicMock(status_code=401, content=b'{"detail":"bad signature"}',
                         headers={"content-type": "application/json"})
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=upstream)
    with patch.object(wa.httpx, "AsyncClient", return_value=client):
        res = await anon_client.post(
            f"/api/webhooks/whatsapp/{sample_agent.slug}/inbound", content=b"{}")
    assert res.status_code == 401  # the plugin's verdict, not ours


