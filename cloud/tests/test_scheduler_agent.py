"""Plan 035 — agent-facing scheduler self-service (device-token authed)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cloud.scheduler_svc.provision as prov
from cloud import config
from cloud.gateway.tokens import issue_token


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "scheduler_service_url", "https://sched.example.com", raising=False)
    monkeypatch.setattr(s, "scheduler_service_admin_key", "test-key", raising=False)
    monkeypatch.setattr(s, "base_url", "https://luna.test", raising=False)


def _svc_response(status_code=201, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = "svc"
    return resp


async def _token(db_session, agent):
    return await issue_token(db_session, agent.id)


@pytest.mark.asyncio
async def test_connect_provisions_own_account(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    svc = AsyncMock(return_value=_svc_response(201, {
        "account_id": sample_agent.slug, "secret": "per-agent-s3cret", "status": "active",
    }))
    with patch.object(prov, "_service", svc):
        res = await anon_client.post(
            "/api/agent/scheduler/connect",
            headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    body = res.json()
    assert body["account_id"] == sample_agent.slug
    assert body["secret"] == "per-agent-s3cret"
    assert body["service_url"] == "https://sched.example.com"
    # account id forced server-side from the token's agent
    method, path, payload = svc.call_args[0]
    assert payload["account_id"] == sample_agent.slug
    assert payload["fire_url"] == (
        f"https://luna.test/api/webhooks/scheduler/{sample_agent.slug}/fire")


@pytest.mark.asyncio
async def test_connect_records_plugin_membership(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    with patch.object(prov, "_service", AsyncMock(return_value=_svc_response(
            201, {"account_id": sample_agent.slug, "status": "active"}))):
        await anon_client.post("/api/agent/scheduler/connect",
                               headers={"Authorization": f"Bearer {tok}"})
    await db_session.refresh(sample_agent)
    assert "plugin-scheduler" in (sample_agent.config_overrides or {}).get("installed_plugins", [])


@pytest.mark.asyncio
async def test_reconnect_without_secret(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    with patch.object(prov, "_service", AsyncMock(return_value=_svc_response(
            200, {"account_id": sample_agent.slug, "status": "active"}))):
        res = await anon_client.post("/api/agent/scheduler/connect",
                                     headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    assert "secret" not in res.json()


@pytest.mark.asyncio
async def test_connect_rotate_recovers_lost_secret(anon_client, db_session, sample_agent):
    """Vault wiped: account exists (connect returns no secret) — rotate mints
    a fresh one via PATCH and returns it once."""
    tok = await _token(db_session, sample_agent)
    svc = AsyncMock(side_effect=[
        _svc_response(200, {"account_id": sample_agent.slug, "created": False}),
        _svc_response(200, {"account_id": sample_agent.slug, "secret": "fresh-s3cret"}),
    ])
    with patch.object(prov, "_service", svc):
        res = await anon_client.post(
            "/api/agent/scheduler/connect", json={"rotate": True},
            headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    assert res.json()["secret"] == "fresh-s3cret"
    method, path, payload = svc.call_args_list[1][0]
    assert (method, path) == ("PATCH", f"/accounts/{sample_agent.slug}")
    assert payload == {"rotate_secret": True}


@pytest.mark.asyncio
async def test_connect_rotate_skipped_on_fresh_create(anon_client, db_session, sample_agent):
    """First-ever connect already returns a secret — rotate must not
    invalidate it with a second PATCH."""
    tok = await _token(db_session, sample_agent)
    svc = AsyncMock(return_value=_svc_response(201, {
        "account_id": sample_agent.slug, "secret": "first-s3cret", "created": True}))
    with patch.object(prov, "_service", svc):
        res = await anon_client.post(
            "/api/agent/scheduler/connect", json={"rotate": True},
            headers={"Authorization": f"Bearer {tok}"})
    assert res.json()["secret"] == "first-s3cret"
    assert svc.call_count == 1


@pytest.mark.asyncio
async def test_connect_without_rotate_never_patches(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    svc = AsyncMock(return_value=_svc_response(
        200, {"account_id": sample_agent.slug, "created": False}))
    with patch.object(prov, "_service", svc):
        res = await anon_client.post("/api/agent/scheduler/connect",
                                     headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200 and "secret" not in res.json()
    assert svc.call_count == 1


@pytest.mark.asyncio
async def test_connect_requires_token(anon_client):
    assert (await anon_client.post("/api/agent/scheduler/connect")).status_code == 401
    res = await anon_client.post("/api/agent/scheduler/connect",
                                 headers={"Authorization": "Bearer lsv1-bogus"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_connect_unconfigured_503(anon_client, db_session, sample_agent, monkeypatch):
    monkeypatch.setattr(config.get_settings(), "scheduler_service_url", "", raising=False)
    tok = await _token(db_session, sample_agent)
    res = await anon_client.post("/api/agent/scheduler/connect",
                                 headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_status_slice(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    acct = {"account_id": sample_agent.slug, "enabled": True, "triggers": 3,
            "next_run_at": "2026-07-06T12:05:00Z", "last_fire_at": None,
            "last_fire_status": None, "fires_24h": 7, "sent_today": 7, "daily_cap": 200}
    with patch.object(prov, "_service", AsyncMock(return_value=_svc_response(200, acct))):
        body = (await anon_client.get("/api/agent/scheduler/status",
                                      headers={"Authorization": f"Bearer {tok}"})).json()
    assert body["exists"] and body["triggers"] == 3 and body["fires_24h"] == 7


@pytest.mark.asyncio
async def test_status_missing_account(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    with patch.object(prov, "_service", AsyncMock(return_value=_svc_response(404))):
        body = (await anon_client.get("/api/agent/scheduler/status",
                                      headers={"Authorization": f"Bearer {tok}"})).json()
    assert body == {"exists": False}


@pytest.mark.asyncio
async def test_disconnect_own_account(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    with patch.object(prov, "_service", AsyncMock(return_value=_svc_response(204))) as svc:
        res = await anon_client.delete("/api/agent/scheduler/connect",
                                       headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200 and res.json()["deleted"]
    assert svc.call_args[0][1] == f"/accounts/{sample_agent.slug}"


@pytest.mark.asyncio
async def test_connect_reachable_under_proxy_prefix(anon_client, db_session, sample_agent):
    """LUNA_GATEWAY_URL is '<host>/proxy'; agent-API callers may append the
    agent path without stripping the suffix — the /proxy alias must answer
    identically (the 034.1 plugin-v0.8.0 lesson)."""
    tok = await _token(db_session, sample_agent)
    with patch.object(prov, "_service", AsyncMock(return_value=_svc_response(
            201, {"account_id": sample_agent.slug, "status": "active"}))):
        res = await anon_client.post("/proxy/api/agent/scheduler/connect",
                                     headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    assert res.json()["account_id"] == sample_agent.slug
