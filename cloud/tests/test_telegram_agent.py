"""Plan 045 — tenant-authenticated Telegram account lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

import cloud.telegram.provision as provision
from cloud import config
from cloud.db.models import PluginCatalogEntry
from cloud.gateway.tokens import issue_token

BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    settings = config.get_settings()
    monkeypatch.setattr(
        settings,
        "telegram_gateway_url",
        "https://telegram-gateway.example.com",
        raising=False,
    )
    monkeypatch.setattr(
        settings, "telegram_gateway_admin_key", "gateway-admin-secret", raising=False
    )
    monkeypatch.setattr(
        settings, "telegram_plugin_marketplace_url", "", raising=False
    )
    monkeypatch.setattr(settings, "base_url", "https://luna.test", raising=False)


def _gateway_response(status_code=201, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    return response


async def _token(db_session, agent):
    return await issue_token(db_session, agent.id)


@pytest.mark.asyncio
async def test_connect_forces_slug_and_returns_one_time_plugin_config(
    anon_client, db_session, sample_agent
):
    token = await _token(db_session, sample_agent)
    gateway = AsyncMock(
        return_value=_gateway_response(
            201,
            {
                "ok": True,
                "account": {
                    "account_id": sample_agent.slug,
                    "status": "active",
                    "bot_id": 123,
                    "bot_username": "test_luna_bot",
                    "bot_name": "Luna",
                    "can_join_groups": True,
                    "can_read_all_group_messages": False,
                    "supports_inline_queries": True,
                },
                "shared_secret": "per-account-secret",
            },
        )
    )
    with patch.object(provision, "_gateway", gateway):
        response = await anon_client.post(
            "/api/agent/telegram/connect",
            json={"bot_token": BOT_TOKEN, "account_id": "victim"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json() == {
        "account_id": sample_agent.slug,
        "gateway_url": "https://telegram-gateway.example.com",
        "bot": {
            "id": 123,
            "username": "test_luna_bot",
            "name": "Luna",
            "first_name": "Luna",
            "can_join_groups": True,
            "can_read_all_group_messages": False,
            "supports_inline_queries": True,
        },
        "status": "active",
        "shared_secret": "per-account-secret",
    }
    method, path, payload = gateway.call_args.args
    assert (method, path) == ("POST", "/accounts")
    assert payload == {
        "account_id": sample_agent.slug,
        "bot_token": BOT_TOKEN,
        "inbound_url": (
            f"https://luna.test/api/webhooks/telegram/{sample_agent.slug}/inbound"
        ),
    }


@pytest.mark.asyncio
async def test_connect_records_plugin_without_persisting_bot_token(
    anon_client, db_session, sample_agent
):
    token = await _token(db_session, sample_agent)
    gateway_body = {
        "ok": True,
        "account": {
            "account_id": sample_agent.slug,
            "status": "active",
            "bot_id": 123,
            "bot_username": "test_luna_bot",
        },
        "shared_secret": "per-account-secret",
    }
    with patch.object(
        provision,
        "_gateway",
        AsyncMock(return_value=_gateway_response(201, gateway_body)),
    ):
        response = await anon_client.post(
            "/api/agent/telegram/connect",
            json={"bot_token": BOT_TOKEN},
            headers={"Authorization": f"Bearer {token}"},
        )
    await db_session.refresh(sample_agent)
    overrides = sample_agent.config_overrides or {}
    assert "plugin-telegram" in overrides.get("installed_plugins", [])
    assert BOT_TOKEN not in str(overrides)
    assert BOT_TOKEN not in response.text


@pytest.mark.asyncio
async def test_connect_errors_are_tenant_facing_and_create_no_plugin_record(
    anon_client, db_session, sample_agent, caplog
):
    cases = [
        (400, {"error": "invalid_bot_token"}, 400, "Invalid BotFather token"),
        (
            409,
            {"ok": False, "error": "bot_already_connected"},
            409,
            "already connected to another Luna",
        ),
        (
            503,
            {
                "ok": False,
                "error": {
                    "code": "PUBLIC_URL_NOT_CONFIGURED",
                    "message": "PUBLIC_URL is required",
                },
            },
            503,
            "public URL is not configured",
        ),
    ]
    for gateway_status, gateway_body, expected_status, expected_detail in cases:
        token = await _token(db_session, sample_agent)
        with patch.object(
            provision,
            "_gateway",
            AsyncMock(
                return_value=_gateway_response(gateway_status, gateway_body)
            ),
        ):
            response = await anon_client.post(
                "/api/agent/telegram/connect",
                json={"bot_token": BOT_TOKEN},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == expected_status
        assert expected_detail in response.json()["detail"]
        assert BOT_TOKEN not in response.text
    await db_session.refresh(sample_agent)
    assert "plugin-telegram" not in (
        sample_agent.config_overrides or {}
    ).get("installed_plugins", [])
    assert BOT_TOKEN not in caplog.text
    assert BOT_TOKEN not in response.text


@pytest.mark.asyncio
async def test_connect_requires_token_and_gateway_configuration(
    anon_client, db_session, sample_agent, monkeypatch
):
    assert (
        await anon_client.post(
            "/api/agent/telegram/connect", json={"bot_token": BOT_TOKEN}
        )
    ).status_code == 401
    token = await _token(db_session, sample_agent)
    monkeypatch.setattr(
        config.get_settings(), "telegram_gateway_url", "", raising=False
    )
    response = await anon_client.post(
        "/api/agent/telegram/connect",
        json={"bot_token": BOT_TOKEN},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_status_reads_only_authenticated_slug(
    anon_client, db_session, sample_agent
):
    token = await _token(db_session, sample_agent)
    account = {
        "account": {
            "account_id": sample_agent.slug,
            "status": "active",
            "enabled": True,
            "bot_id": 123,
            "bot_username": "test_luna_bot",
            "bot_name": "Luna",
            "can_join_groups": True,
            "can_read_all_group_messages": False,
            "supports_inline_queries": False,
            "webhook": {
                "url": "https://gateway.example.com/tg/account",
                "pending_update_count": 0,
                "last_error_date": None,
                "last_error_message": None,
            },
            "messages_24h": 7,
            "chats_24h": 3,
            "forward_failures": 1,
        }
    }
    gateway = AsyncMock(return_value=_gateway_response(200, account))
    with patch.object(provision, "_gateway", gateway):
        response = await anon_client.get(
            "/api/agent/telegram/status?account_id=victim",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["account_id"] == sample_agent.slug
    assert response.json()["bot"]["username"] == "test_luna_bot"
    assert response.json()["bot"]["name"] == "Luna"
    assert response.json()["webhook"]["configured"] is True
    assert response.json()["messages_24h_in"] == 7
    assert response.json()["messages_24h_out"] == 0
    assert response.json()["group_visibility"] == "mentions only"
    assert gateway.call_args.args[1] == f"/accounts/{sample_agent.slug}"


@pytest.mark.asyncio
async def test_status_missing_account(anon_client, db_session, sample_agent):
    token = await _token(db_session, sample_agent)
    with patch.object(
        provision,
        "_gateway",
        AsyncMock(return_value=_gateway_response(404)),
    ):
        response = await anon_client.get(
            "/api/agent/telegram/status",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.json() == {"exists": False}


@pytest.mark.asyncio
async def test_disconnect_deletes_only_authenticated_slug(
    anon_client, db_session, sample_agent
):
    token = await _token(db_session, sample_agent)
    gateway = AsyncMock(return_value=_gateway_response(204))
    with patch.object(provision, "_gateway", gateway):
        response = await anon_client.delete(
            "/api/agent/telegram/connect?account_id=victim",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert gateway.call_args.args[1] == f"/accounts/{sample_agent.slug}"


@pytest.mark.asyncio
async def test_proxy_alias_connects(anon_client, db_session, sample_agent):
    token = await _token(db_session, sample_agent)
    body = {
        "ok": True,
        "account": {
            "account_id": sample_agent.slug,
            "status": "active",
            "bot_id": 123,
            "bot_username": "test_luna_bot",
        },
        "shared_secret": "per-account-secret",
    }
    with patch.object(
        provision,
        "_gateway",
        AsyncMock(return_value=_gateway_response(201, body)),
    ):
        response = await anon_client.post(
            "/proxy/api/agent/telegram/connect",
            json={"bot_token": BOT_TOKEN},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["account_id"] == sample_agent.slug


@pytest.mark.asyncio
async def test_no_admin_connect_ui_routes(admin_client, sample_agent):
    response = await admin_client.post(
        f"/api/admin/telegram/instances/{sample_agent.id}/connect",
        json={"bot_token": BOT_TOKEN},
    )
    assert response.status_code in (404, 405)


@pytest.mark.asyncio
async def test_catalog_entry_requires_real_marketplace_url(
    db_session, monkeypatch
):
    await provision.seed_supported_plugin(db_session)
    assert (
        await db_session.execute(
            select(PluginCatalogEntry).where(
                PluginCatalogEntry.plugin_name == "plugin-telegram"
            )
        )
    ).scalar_one_or_none() is None

    monkeypatch.setattr(
        config.get_settings(),
        "telegram_plugin_marketplace_url",
        "https://marketplaces.com.ai/mp/official/",
        raising=False,
    )
    await provision.seed_supported_plugin(db_session)
    await db_session.commit()
    entry = (
        await db_session.execute(
            select(PluginCatalogEntry).where(
                PluginCatalogEntry.plugin_name == "plugin-telegram"
            )
        )
    ).scalar_one()
    assert entry.tier == "supported"
    assert entry.marketplace_url == "https://marketplaces.com.ai/mp/official/"
