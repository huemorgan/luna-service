"""Plan 035 — scheduler service monitoring routes + fire relay."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cloud.api.scheduler_routes as sched
from cloud import config

SERVICE_STATS = {
    "version": "0.1.0",
    "uptime_s": 3600,
    "last_tick_at": "2026-07-06T12:00:00Z",
    "db": {"ok": True, "latency_ms": 4},
    "totals": {"accounts": 2, "triggers_enabled": 3, "triggers_paused": 1,
               "fires_1h": 2, "fires_24h": 40, "failed_24h": 1, "dead_24h": 0},
    "upcoming": [
        {"due_at": "2026-07-06T12:05:00Z", "account_id": "test-account-test-agent",
         "trigger_name": "morning summary"},
    ],
    "accounts": [
        {"account_id": "test-account-test-agent", "enabled": True, "triggers": 2,
         "next_run_at": "2026-07-06T12:05:00Z", "last_fire_at": "2026-07-06T11:05:00Z",
         "last_fire_status": "delivered", "fires_24h": 24, "sent_today": 5,
         "daily_cap": 200},
        {"account_id": "someone-else", "enabled": True, "triggers": 2},
    ],
}


def _settings():
    return config.get_settings()


@pytest.fixture(autouse=True)
def _reset_cache_and_config(monkeypatch):
    sched._stats_cache = None
    s = _settings()
    monkeypatch.setattr(s, "scheduler_service_url", "https://sched.example.com", raising=False)
    monkeypatch.setattr(s, "scheduler_service_admin_key", "test-key", raising=False)
    yield
    sched._stats_cache = None


def _mock_service(status_code=200, json_body=None, exc=None):
    """Patch httpx.AsyncClient used by the routes module."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else SERVICE_STATS
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if exc:
        client.get = AsyncMock(side_effect=exc)
    else:
        client.get = AsyncMock(return_value=resp)
    return patch.object(sched.httpx, "AsyncClient", return_value=client), client


# ── auth ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_requires_admin(regular_client):
    assert (await regular_client.get("/api/admin/scheduler/stats")).status_code == 403


@pytest.mark.asyncio
async def test_stats_requires_auth(anon_client):
    assert (await anon_client.get("/api/admin/scheduler/stats")).status_code == 401


# ── config states ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unconfigured(admin_client, monkeypatch):
    monkeypatch.setattr(_settings(), "scheduler_service_url", "", raising=False)
    res = await admin_client.get("/api/admin/scheduler/stats")
    assert res.status_code == 200
    assert res.json() == {"configured": False}


# ── proxy behavior ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_ok(admin_client):
    patcher, client = _mock_service()
    with patcher:
        res = await admin_client.get("/api/admin/scheduler/stats")
    body = res.json()
    assert res.status_code == 200
    assert body["configured"] and body["reachable"] and body["authorized"]
    assert body["stats"]["totals"]["triggers_enabled"] == 3
    # admin key sent upstream as header, never echoed back
    _, kwargs = client.get.call_args
    assert kwargs["headers"]["x-admin-key"] == "test-key"
    assert "test-key" not in res.text


@pytest.mark.asyncio
async def test_stats_unauthorized_upstream(admin_client):
    patcher, _ = _mock_service(status_code=401)
    with patcher:
        body = (await admin_client.get("/api/admin/scheduler/stats")).json()
    assert body == {"configured": True, "reachable": True, "authorized": False}


@pytest.mark.asyncio
async def test_stats_unreachable_is_200(admin_client):
    patcher, _ = _mock_service(exc=sched.httpx.ConnectError("boom"))
    with patcher:
        res = await admin_client.get("/api/admin/scheduler/stats")
    assert res.status_code == 200
    assert res.json() == {"configured": True, "reachable": False}


@pytest.mark.asyncio
async def test_stats_cached_within_ttl(admin_client):
    patcher, client = _mock_service()
    with patcher:
        await admin_client.get("/api/admin/scheduler/stats")
        await admin_client.get("/api/admin/scheduler/stats")
        await admin_client.get("/api/admin/scheduler/stats")
    assert client.get.call_count == 1


# ── triggers list ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_triggers_list(admin_client):
    rows = [{"id": "t1", "account_id": "a", "name": "n", "expr_raw": "every minute",
             "expr_cron": "* * * * *", "timezone": "UTC", "action_type": "playbook",
             "target": "x", "enabled": True, "next_run_at": None, "last_run_at": None}]
    patcher, _ = _mock_service(json_body=rows)
    with patcher:
        body = (await admin_client.get("/api/admin/scheduler/triggers")).json()
    assert body["triggers"] == rows
    assert "stats" not in body


@pytest.mark.asyncio
async def test_triggers_unconfigured(admin_client, monkeypatch):
    monkeypatch.setattr(_settings(), "scheduler_service_url", "", raising=False)
    body = (await admin_client.get("/api/admin/scheduler/triggers")).json()
    assert body == {"configured": False}


# ── instances ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_instances_joins_service_accounts(admin_client, sample_agent):
    with patch.object(sched, "_fetch_service", AsyncMock(return_value={
        "configured": True, "reachable": True, "authorized": True, "stats": SERVICE_STATS,
    })):
        rows = (await admin_client.get("/api/admin/scheduler/instances")).json()
    row = next(r for r in rows if r["slug"] == sample_agent.slug)
    assert row["account"]["triggers"] == 2
    assert row["account"]["last_fire_status"] == "delivered"


@pytest.mark.asyncio
async def test_instances_reports_plugin_membership(admin_client, db_session, sample_agent):
    sample_agent.config_overrides = {"installed_plugins": ["plugin-scheduler"]}
    db_session.add(sample_agent)
    await db_session.commit()
    with patch.object(sched, "_fetch_service", AsyncMock(return_value={
        "configured": True, "reachable": True, "authorized": True,
        "stats": {**SERVICE_STATS, "accounts": []},
    })):
        rows = (await admin_client.get("/api/admin/scheduler/instances")).json()
    assert rows[0]["plugin_installed"] is True
    assert rows[0]["account"] is None


# ── fire relay ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_relay_forwards_raw_body_and_hmac_headers(anon_client, sample_agent):
    upstream = MagicMock(status_code=200, content=b'{"deduped":false}',
                         headers={"content-type": "application/json"})
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=upstream)

    with patch.object(sched.httpx, "AsyncClient", return_value=client):
        res = await anon_client.post(
            f"/api/webhooks/scheduler/{sample_agent.slug}/fire",
            content=b'{"fire_id":"f1"}',
            headers={"x-sched-timestamp": "123", "x-sched-signature": "abc",
                     "content-type": "application/json"},
        )

    assert res.status_code == 200 and res.json() == {"deduped": False}
    args, kwargs = client.post.call_args
    assert args[0].endswith("/api/p/plugin-scheduler/fire")
    assert kwargs["content"] == b'{"fire_id":"f1"}'
    assert kwargs["headers"]["x-sched-timestamp"] == "123"
    assert kwargs["headers"]["x-sched-signature"] == "abc"
    assert kwargs["headers"]["fly-force-instance-id"] == sample_agent.runtime_ref
    assert "x-luna-proxy-secret" in kwargs["headers"]


@pytest.mark.asyncio
async def test_relay_unknown_slug_404(anon_client):
    res = await anon_client.post("/api/webhooks/scheduler/nope/fire", content=b"{}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_relay_passes_through_plugin_403(anon_client, sample_agent):
    upstream = MagicMock(status_code=403, content=b'{"detail":"bad signature"}',
                         headers={"content-type": "application/json"})
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=upstream)
    with patch.object(sched.httpx, "AsyncClient", return_value=client):
        res = await anon_client.post(
            f"/api/webhooks/scheduler/{sample_agent.slug}/fire", content=b"{}")
    assert res.status_code == 403  # the plugin's verdict, not ours
