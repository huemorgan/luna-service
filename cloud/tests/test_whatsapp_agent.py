"""Plan 034.1 — agent-facing WhatsApp self-service (device-token authed)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cloud.whatsapp.provision as prov
from cloud import config
from cloud.gateway.tokens import issue_token


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "whatsapp_gateway_url", "https://wa.example.com", raising=False)
    monkeypatch.setattr(s, "whatsapp_gateway_admin_key", "test-key", raising=False)
    monkeypatch.setattr(s, "base_url", "https://luna.test", raising=False)


def _gw_response(status_code=201, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = "gw"
    resp.content = b"gw"
    resp.headers = {"content-type": "application/json"}
    return resp


async def _token(db_session, agent):
    return await issue_token(db_session, agent.id)


@pytest.mark.asyncio
async def test_connect_provisions_own_account(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    gw = AsyncMock(return_value=_gw_response(201, {
        "account_id": sample_agent.slug, "secret": "per-agent-s3cret", "status": "linking",
    }))
    with patch.object(prov, "_gateway", gw):
        res = await anon_client.post(
            "/api/agent/whatsapp/connect",
            headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    body = res.json()
    assert body["account_id"] == sample_agent.slug
    assert body["secret"] == "per-agent-s3cret"
    assert body["gateway_url"] == "https://wa.example.com"
    # account id forced server-side from the token's agent
    method, path, payload = gw.call_args[0]
    assert payload["account_id"] == sample_agent.slug
    assert payload["inbound_url"] == (
        f"https://luna.test/api/webhooks/whatsapp/{sample_agent.slug}/inbound")


@pytest.mark.asyncio
async def test_connect_records_plugin_membership(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    with patch.object(prov, "_gateway", AsyncMock(return_value=_gw_response(
            201, {"account_id": sample_agent.slug, "status": "linking"}))):
        await anon_client.post("/api/agent/whatsapp/connect",
                               headers={"Authorization": f"Bearer {tok}"})
    await db_session.refresh(sample_agent)
    assert "plugin-whatsapp" in (sample_agent.config_overrides or {}).get("installed_plugins", [])


@pytest.mark.asyncio
async def test_reconnect_without_secret(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    with patch.object(prov, "_gateway", AsyncMock(return_value=_gw_response(
            200, {"account_id": sample_agent.slug, "status": "linking"}))):
        res = await anon_client.post("/api/agent/whatsapp/connect",
                                     headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    assert "secret" not in res.json()


@pytest.mark.asyncio
async def test_connect_requires_token(anon_client):
    assert (await anon_client.post("/api/agent/whatsapp/connect")).status_code == 401
    res = await anon_client.post("/api/agent/whatsapp/connect",
                                 headers={"Authorization": "Bearer lsv1-bogus"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_connect_unconfigured_503(anon_client, db_session, sample_agent, monkeypatch):
    monkeypatch.setattr(config.get_settings(), "whatsapp_gateway_url", "", raising=False)
    tok = await _token(db_session, sample_agent)
    res = await anon_client.post("/api/agent/whatsapp/connect",
                                 headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_qr_is_own_account(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    qr = MagicMock(status_code=200, text="<html>my-qr</html>")
    with patch.object(prov, "_gateway", AsyncMock(return_value=qr)) as gw:
        res = await anon_client.get("/api/agent/whatsapp/qr",
                                    headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200 and "my-qr" in res.text
    assert gw.call_args[0][1] == f"/accounts/{sample_agent.slug}/qr?format=html"


@pytest.mark.asyncio
async def test_status_slice(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    acct = {"account_id": sample_agent.slug, "status": "open", "connected": True,
            "self_jid": "972@s.whatsapp.net", "has_qr": False,
            "sent_today": 5, "daily_cap": 300}
    with patch.object(prov, "_gateway", AsyncMock(return_value=_gw_response(200, acct))):
        body = (await anon_client.get("/api/agent/whatsapp/status",
                                      headers={"Authorization": f"Bearer {tok}"})).json()
    assert body["exists"] and body["connected"] and body["sent_today"] == 5


@pytest.mark.asyncio
async def test_status_missing_account(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    with patch.object(prov, "_gateway", AsyncMock(return_value=_gw_response(404))):
        body = (await anon_client.get("/api/agent/whatsapp/status",
                                      headers={"Authorization": f"Bearer {tok}"})).json()
    assert body == {"exists": False}


@pytest.mark.asyncio
async def test_disconnect_own_account(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    with patch.object(prov, "_gateway", AsyncMock(return_value=_gw_response(204))) as gw:
        res = await anon_client.delete("/api/agent/whatsapp/connect",
                                       headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200 and res.json()["deleted"]
    assert gw.call_args[0][1] == f"/accounts/{sample_agent.slug}"


# ── deleted admin routes stay deleted ────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_connect_routes_are_gone(admin_client, sample_agent):
    assert (await admin_client.post(
        f"/api/admin/whatsapp/instances/{sample_agent.id}/connect")).status_code in (404, 405)
    assert (await admin_client.get(
        f"/api/admin/whatsapp/instances/{sample_agent.id}/qr")).status_code == 404
    assert (await admin_client.post(
        "/api/admin/whatsapp/env/backfill")).status_code in (404, 405)
