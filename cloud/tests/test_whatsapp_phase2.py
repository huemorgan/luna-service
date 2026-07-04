"""Plan 034 Phase 2 — per-instance connect flow + inbound relay."""

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


# ── connect flow ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_creates_account_and_writes_vault(admin_client, sample_agent):
    gw_resp = _gw_response(201, {
        "account_id": sample_agent.slug, "secret": "s3cr3t-abc", "status": "linking",
    })
    tenant_calls = []

    async def fake_tenant_request(agent, method, path, body=None, *, user_email, timeout=25.0):
        tenant_calls.append((method, path, body, user_email))
        return 200, {"ok": True}

    with patch.object(prov, "_gateway", AsyncMock(return_value=gw_resp)) as gw, \
         patch("cloud.api.agent_routes._tenant_request", side_effect=fake_tenant_request):
        res = await admin_client.post(
            f"/api/admin/whatsapp/instances/{sample_agent.id}/connect")

    assert res.status_code == 200
    body = res.json()
    assert body["secret_stored"] and body["account_id_stored"] and body["plugin_installed"]
    assert body["qr_path"].endswith(f"/instances/{sample_agent.id}/qr")

    # gateway account created with our relay as inbound
    _, kwargs = (gw.call_args[0], gw.call_args[0])
    method, path, payload = gw.call_args[0]
    assert (method, path) == ("POST", "/accounts")
    assert payload["account_id"] == sample_agent.slug
    assert payload["inbound_url"] == (
        f"https://luna.test/api/webhooks/whatsapp/{sample_agent.slug}/inbound")

    # vault writes: secret + account id, then plugin install — all trusted-proxy
    paths = [c[1] for c in tenant_calls]
    assert paths == [
        "/api/p/plugin-vault/credentials",
        "/api/p/plugin-vault/credentials",
        "/api/p/plugin-marketplace/install",
    ]
    names = [c[2].get("name") for c in tenant_calls[:2]]
    assert names == ["plugin_whatsapp.shared_secret", "plugin_whatsapp.account_id"]
    assert tenant_calls[0][2]["value"] == "s3cr3t-abc"
    assert tenant_calls[1][2]["value"] == sample_agent.slug
    # the secret never appears in the HTTP response
    assert "s3cr3t-abc" not in res.text


@pytest.mark.asyncio
async def test_connect_idempotent_without_secret(admin_client, sample_agent):
    """Re-connect: gateway returns no secret → no secret vault write, no failure."""
    gw_resp = _gw_response(200, {"account_id": sample_agent.slug, "status": "linking"})
    tenant_calls = []

    async def fake_tenant_request(agent, method, path, body=None, *, user_email, timeout=25.0):
        tenant_calls.append(path)
        return 200, {}

    with patch.object(prov, "_gateway", AsyncMock(return_value=gw_resp)), \
         patch("cloud.api.agent_routes._tenant_request", side_effect=fake_tenant_request):
        res = await admin_client.post(
            f"/api/admin/whatsapp/instances/{sample_agent.id}/connect")

    assert res.status_code == 200
    assert res.json()["secret_stored"] is False
    assert tenant_calls.count("/api/p/plugin-vault/credentials") == 1  # account id only


@pytest.mark.asyncio
async def test_connect_gateway_error_is_502(admin_client, sample_agent):
    with patch.object(prov, "_gateway", AsyncMock(return_value=_gw_response(500))):
        res = await admin_client.post(
            f"/api/admin/whatsapp/instances/{sample_agent.id}/connect")
    assert res.status_code == 502


@pytest.mark.asyncio
async def test_connect_requires_admin(regular_client, sample_agent):
    res = await regular_client.post(
        f"/api/admin/whatsapp/instances/{sample_agent.id}/connect")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_disconnect(admin_client, sample_agent):
    with patch.object(prov, "_gateway", AsyncMock(return_value=_gw_response(204))) as gw:
        res = await admin_client.delete(
            f"/api/admin/whatsapp/instances/{sample_agent.id}/connect")
    assert res.status_code == 200 and res.json()["deleted"]
    method, path = gw.call_args[0][0], gw.call_args[0][1]
    assert (method, path) == ("DELETE", f"/accounts/{sample_agent.slug}")


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


# ── per-instance QR proxy ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_instance_qr_proxies_account_qr(admin_client, sample_agent):
    qr = MagicMock(status_code=200, text="<html>account-qr</html>")
    with patch.object(prov, "_gateway", AsyncMock(return_value=qr)) as gw:
        res = await admin_client.get(f"/api/admin/whatsapp/instances/{sample_agent.id}/qr")
    assert res.status_code == 200 and "account-qr" in res.text
    assert gw.call_args[0][1] == f"/accounts/{sample_agent.slug}/qr?format=html"


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


# ── Phase 3: env backfill + reconcile ────────────────────────────────────────

@pytest.mark.asyncio
async def test_backfill_dry_run_reports_missing(admin_client, sample_agent, monkeypatch):
    monkeypatch.setenv("FLY_API_TOKEN", "t")
    accounts_resp = _gw_response(200, {"accounts": [
        {"account_id": "ghost-agent", "status": "linking"},
        {"account_id": "default", "status": "linking"},
        {"account_id": sample_agent.slug, "status": "linking"},
    ]})
    fly = MagicMock()
    fly.describe = AsyncMock(return_value={"config": {"env": {"LUNA_ENV": "prod"}}})
    fly.update_machine_env = AsyncMock()
    with patch.object(prov, "_gateway", AsyncMock(return_value=accounts_resp)), \
         patch("cloud.runtime.fly_machines.FlyMachinesRuntime", return_value=fly):
        res = await admin_client.post("/api/admin/whatsapp/env/backfill?dry_run=true")
    body = res.json()
    assert body["dry_run"] is True
    assert body["machines"][0]["status"] == "would_update"
    fly.update_machine_env.assert_not_called()
    # default + matching slug excluded; ghost reported
    assert body["orphan_accounts"] == ["ghost-agent"]


@pytest.mark.asyncio
async def test_backfill_pushes_only_whatsapp_var(admin_client, sample_agent, monkeypatch):
    monkeypatch.setenv("FLY_API_TOKEN", "t")
    fly = MagicMock()
    fly.describe = AsyncMock(return_value={"config": {"env": {}}})
    fly.update_machine_env = AsyncMock()
    with patch.object(prov, "_gateway", AsyncMock(return_value=_gw_response(200, {"accounts": []}))), \
         patch("cloud.runtime.fly_machines.FlyMachinesRuntime", return_value=fly):
        res = await admin_client.post("/api/admin/whatsapp/env/backfill?dry_run=false")
    assert res.json()["updated"] == 1
    fly.update_machine_env.assert_called_once_with(
        sample_agent.runtime_ref, {"LUNA_WHATSAPP_GATEWAY_URL": "https://wa.example.com"})


@pytest.mark.asyncio
async def test_backfill_skips_up_to_date(admin_client, sample_agent, monkeypatch):
    monkeypatch.setenv("FLY_API_TOKEN", "t")
    fly = MagicMock()
    fly.describe = AsyncMock(return_value={"config": {"env": {"LUNA_WHATSAPP_GATEWAY_URL": "x"}}})
    fly.update_machine_env = AsyncMock()
    with patch.object(prov, "_gateway", AsyncMock(return_value=_gw_response(200, {"accounts": []}))), \
         patch("cloud.runtime.fly_machines.FlyMachinesRuntime", return_value=fly):
        res = await admin_client.post("/api/admin/whatsapp/env/backfill?dry_run=false")
    assert res.json()["skipped"] == 1 and res.json()["updated"] == 0
    fly.update_machine_env.assert_not_called()
