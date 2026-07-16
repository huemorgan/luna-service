"""Plan 045 — Telegram admin monitoring and inbound relay."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cloud.api.telegram_routes as telegram
from cloud import config

BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
GATEWAY_STATS = {
    "ok": True,
    "status": "ok",
    "version": "0.2.0",
    "uptime_s": 3600,
    "db": {"ok": True, "latency_ms": 5},
    "webhook": {
        "url": "https://gateway.example.com/tg/webhook",
        "pending_update_count": 2,
        "last_error_date": 1_752_665_600,
        "last_error_message": "previous delivery failed",
    },
    "totals": {
        "accounts": 2,
        "active_chats": 8,
        "messages_24h_in": 15,
        "messages_24h_out": 12,
        "forward_failures_24h": 1,
    },
    "hourly": [{"hour": "2026-07-16T12:00:00Z", "in": 4, "out": 3}],
    "accounts": [
        {
            "account_id": "test-account-test-agent",
            "status": "active",
            "bot_id": 123,
            "bot_username": "test_luna_bot",
            "bot_name": "Luna",
            "can_join_groups": True,
            "can_read_all_group_messages": False,
            "supports_inline_queries": True,
            "webhook": {
                "url": "https://gateway.example.com/tg/test-account-test-agent",
                "pending_update_count": 0,
                "last_error_date": None,
                "last_error_message": None,
            },
            "last_activity_at": "2026-07-16T12:00:00Z",
            "messages_24h": 7,
            "chats_24h": 4,
            "forward_failures": 1,
        },
        {"account_id": "someone-else", "status": "active"},
    ],
}

GATEWAY_COMPAT_STATS = {
    "status": "ok",
    "gateway_version": "0.2.0-compat",
    "uptime_seconds": 1800,
    "database": {"ok": True, "latency_ms": 8},
    "webhook_url": "https://gateway.example.com/tg/webhook",
    "pending_update_count": 3,
    "messages_24h": 9,
    "chats_24h": 5,
    "forward_failures": 2,
    "accounts": [
        {
            "account_id": "test-account-test-agent",
            "bot": {
                "id": 456,
                "username": "compat_bot",
                "first_name": "Compat",
                "can_join_groups": True,
                "can_read_all_group_messages": True,
            },
            "webhook_configured": True,
            "pending_updates": 1,
            "messages_in_24h": 5,
            "messages_out_24h": 4,
            "active_chats_24h": 5,
            "forward_failures_24h": 2,
        }
    ],
}


def _settings():
    return config.get_settings()


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    telegram._stats_cache = None
    settings = _settings()
    monkeypatch.setattr(
        settings,
        "telegram_gateway_url",
        "https://telegram-gateway.example.com",
        raising=False,
    )
    monkeypatch.setattr(
        settings, "telegram_gateway_admin_key", "gateway-admin-secret", raising=False
    )
    monkeypatch.setattr(settings, "base_url", "https://luna.test", raising=False)
    yield
    telegram._stats_cache = None


def _mock_gateway(status_code=200, json_body=None, exc=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = (
        GATEWAY_STATS if json_body is None else json_body
    )
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = (
        AsyncMock(side_effect=exc)
        if exc
        else AsyncMock(return_value=response)
    )
    return (
        patch.object(telegram.httpx, "AsyncClient", return_value=client),
        client,
    )


@pytest.mark.asyncio
async def test_stats_requires_admin(regular_client, anon_client):
    assert (
        await regular_client.get("/api/admin/telegram/stats")
    ).status_code == 403
    assert (await anon_client.get("/api/admin/telegram/stats")).status_code == 401


@pytest.mark.asyncio
async def test_stats_unconfigured(admin_client, monkeypatch):
    monkeypatch.setattr(_settings(), "telegram_gateway_url", "", raising=False)
    response = await admin_client.get("/api/admin/telegram/stats")
    assert response.status_code == 200
    assert response.json() == {"configured": False}


@pytest.mark.asyncio
async def test_stats_success_is_cached_and_key_stays_server_side(admin_client):
    patcher, client = _mock_gateway()
    with patcher:
        first = await admin_client.get("/api/admin/telegram/stats")
        second = await admin_client.get("/api/admin/telegram/stats")
    assert first.status_code == second.status_code == 200
    stats = first.json()["stats"]
    assert stats["version"] == "0.2.0"
    assert stats["webhook"] == {
        "url": "https://gateway.example.com/tg/webhook",
        "configured": True,
        "pending_updates": 2,
        "last_error": "previous delivery failed",
        "last_error_at": "2025-07-16T11:33:20+00:00",
    }
    assert stats["accounts"][0]["bot"]["supports_inline_queries"] is True
    assert stats["accounts"][0]["privacy_mode"] is True
    assert stats["accounts"][0]["group_visibility"] == "mentions only"
    assert stats["accounts"][0]["messages_24h_in"] == 7
    assert stats["accounts"][0]["messages_24h_out"] == 0
    assert client.get.call_count == 1
    assert client.get.call_args.kwargs["headers"] == {
        "x-admin-key": "gateway-admin-secret"
    }
    assert "gateway-admin-secret" not in first.text

    telegram._stats_cache = None
    compat_patcher, _ = _mock_gateway(json_body=GATEWAY_COMPAT_STATS)
    with compat_patcher:
        compat = (await admin_client.get("/api/admin/telegram/stats")).json()["stats"]
    assert compat["version"] == "0.2.0-compat"
    assert compat["uptime_s"] == 1800
    assert compat["webhook"]["configured"] is True
    assert compat["webhook"]["pending_updates"] == 3
    assert compat["totals"]["messages_24h_in"] == 5
    assert compat["totals"]["messages_24h_out"] == 4
    assert compat["totals"]["active_chats"] == 5
    assert compat["totals"]["forward_failures_24h"] == 2
    assert compat["accounts"][0]["group_visibility"] == "all group messages"


@pytest.mark.asyncio
async def test_stats_redacts_upstream_credentials(admin_client):
    unsafe = {
        **GATEWAY_STATS,
        "admin_key": "gateway-admin-secret",
        "accounts": [
            {
                **GATEWAY_STATS["accounts"][0],
                "bot_token": BOT_TOKEN,
                "shared_secret": "account-secret",
                "error": f"Telegram rejected {BOT_TOKEN}",
            }
        ],
    }
    patcher, _ = _mock_gateway(json_body=unsafe)
    with patcher:
        response = await admin_client.get("/api/admin/telegram/stats")
    assert BOT_TOKEN not in response.text
    assert "gateway-admin-secret" not in response.text
    assert "account-secret" not in response.text
    assert "[redacted]" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_stats_unauthorized_is_graceful(admin_client, status_code):
    patcher, _ = _mock_gateway(status_code=status_code)
    with patcher:
        response = await admin_client.get("/api/admin/telegram/stats")
    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "reachable": True,
        "authorized": False,
    }


@pytest.mark.asyncio
async def test_stats_unreachable_is_graceful(admin_client):
    patcher, _ = _mock_gateway(
        exc=telegram.httpx.ConnectError("gateway-admin-secret")
    )
    with patcher:
        response = await admin_client.get("/api/admin/telegram/stats")
    assert response.status_code == 200
    assert response.json() == {"configured": True, "reachable": False}
    assert "gateway-admin-secret" not in response.text


@pytest.mark.asyncio
async def test_instances_join_only_matching_account(
    admin_client, db_session, sample_agent
):
    sample_agent.config_overrides = {"installed_plugins": ["plugin-telegram"]}
    db_session.add(sample_agent)
    await db_session.commit()
    patcher, _ = _mock_gateway()
    with patcher:
        rows = (await admin_client.get("/api/admin/telegram/instances")).json()
    row = next(item for item in rows if item["slug"] == sample_agent.slug)
    assert row["plugin_installed"] is True
    assert row["account"]["bot"]["username"] == "test_luna_bot"
    assert row["account"]["messages_24h_in"] == 7
    assert row["account"]["messages_24h_out"] == 0
    assert row["account"]["chats_24h"] == 4
    assert row["account"]["forward_failures"] == 1
    assert row["account"]["webhook"]["configured"] is True
    assert row["account"]["group_visibility"] == "mentions only"
    assert "account_id" not in row["account"]


@pytest.mark.asyncio
async def test_relay_preserves_raw_bytes_and_telegram_headers(
    anon_client, sample_agent
):
    upstream = MagicMock(
        status_code=200,
        content=b'{"answered":true}',
        headers={"content-type": "application/json"},
    )
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=upstream)
    raw = b'{ "text": "caf\xc3\xa9", "spaces":  true }\n'
    with patch.object(telegram.httpx, "AsyncClient", return_value=client):
        response = await anon_client.post(
            f"/api/webhooks/telegram/{sample_agent.slug}/inbound",
            content=raw,
            headers={
                "x-tg-account": sample_agent.slug,
                "x-tg-timestamp": "123",
                "x-tg-signature": "abc",
                "content-type": "application/json",
            },
        )
    assert response.status_code == 200
    args, kwargs = client.post.call_args
    assert args[0].endswith("/api/p/plugin-telegram/inbound")
    assert kwargs["content"] == raw
    assert kwargs["headers"]["x-tg-account"] == sample_agent.slug
    assert kwargs["headers"]["x-tg-timestamp"] == "123"
    assert kwargs["headers"]["x-tg-signature"] == "abc"
    assert kwargs["headers"]["fly-force-instance-id"] == sample_agent.runtime_ref
    assert "x-luna-proxy-secret" in kwargs["headers"]


@pytest.mark.asyncio
async def test_relay_unknown_slug_is_404(anon_client):
    response = await anon_client.post(
        "/api/webhooks/telegram/not-an-agent/inbound", content=b"{}"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_relay_wakes_and_retries_once(anon_client, sample_agent):
    upstream = MagicMock(
        status_code=202,
        content=b'{"queued":true}',
        headers={"content-type": "application/json"},
    )
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(
        side_effect=[telegram.httpx.ConnectError("asleep"), upstream]
    )
    with (
        patch.object(telegram.httpx, "AsyncClient", return_value=client),
        patch(
            "cloud.api.proxy._try_wake_agent",
            AsyncMock(return_value=True),
        ) as wake,
    ):
        response = await anon_client.post(
            f"/api/webhooks/telegram/{sample_agent.slug}/inbound",
            content=b"{}",
        )
    assert response.status_code == 202
    assert client.post.call_count == 2
    wake.assert_awaited_once()
