"""Hosted Telegram gateway account provisioning (plan 045).

The control plane forwards a BotFather token to the external multi-account
gateway once. It never stores the token. The gateway returns the per-account
shared secret for the authenticated plugin to persist in its own vault.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud import config
from cloud.db.models import Agent, PluginCatalogEntry

GATEWAY_TIMEOUT_S = 10.0
PLUGIN_NAME = "plugin-telegram"


def _coalesce(*values):
    return next((value for value in values if value is not None), None)


def _iso_timestamp(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return value


def normalize_webhook(webhook: dict | None, fallback: dict | None = None) -> dict:
    """Normalize Telegram's raw getWebhookInfo shape and older compatibility fields."""
    webhook = webhook if isinstance(webhook, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    url = _coalesce(webhook.get("url"), fallback.get("webhook_url"))
    configured = (
        bool(url)
        if url is not None
        else _coalesce(
            webhook.get("configured"), fallback.get("webhook_configured")
        )
    )
    return {
        "url": url,
        "configured": configured,
        "pending_updates": _coalesce(
            webhook.get("pending_update_count"),
            webhook.get("pending_updates"),
            fallback.get("pending_update_count"),
            fallback.get("pending_updates"),
        ),
        "last_error": _coalesce(
            webhook.get("last_error_message"),
            webhook.get("last_error"),
            fallback.get("last_error_message"),
            fallback.get("last_error"),
        ),
        "last_error_at": _iso_timestamp(
            _coalesce(
                webhook.get("last_error_date"),
                webhook.get("last_error_at"),
                fallback.get("last_error_date"),
                fallback.get("last_error_at"),
            )
        ),
    }


def normalize_bot(account: dict) -> dict:
    """Prefer gateway v0.2 flat metadata while retaining nested compatibility."""
    bot = account.get("bot") if isinstance(account.get("bot"), dict) else {}
    name = _coalesce(
        account.get("bot_name"),
        bot.get("name"),
        bot.get("first_name"),
        account.get("bot_first_name"),
    )
    return {
        "id": _coalesce(account.get("bot_id"), bot.get("id")),
        "username": _coalesce(account.get("bot_username"), bot.get("username")),
        "name": name,
        "first_name": name,
        "can_join_groups": _coalesce(
            account.get("can_join_groups"), bot.get("can_join_groups")
        ),
        "can_read_all_group_messages": _coalesce(
            account.get("can_read_all_group_messages"),
            bot.get("can_read_all_group_messages"),
        ),
        "supports_inline_queries": _coalesce(
            account.get("supports_inline_queries"),
            bot.get("supports_inline_queries"),
        ),
    }


def normalize_account(account: dict) -> dict:
    """Map current gateway account rows to the stable control-plane shape."""
    bot = normalize_bot(account)
    webhook = normalize_webhook(account.get("webhook"), account)
    messages_total = _coalesce(
        account.get("messages_24h"), account.get("messages_24h_total")
    )
    messages_in = _coalesce(
        account.get("messages_24h_in"),
        account.get("messages_in_24h"),
        messages_total,
    )
    messages_out = _coalesce(
        account.get("messages_24h_out"),
        account.get("messages_out_24h"),
        0 if messages_total is not None else None,
    )
    privacy_mode = account.get("privacy_mode")
    if privacy_mode is None and isinstance(
        bot["can_read_all_group_messages"], bool
    ):
        privacy_mode = not bot["can_read_all_group_messages"]
    group_visibility = account.get("group_visibility")
    if not group_visibility:
        if bot["can_join_groups"] is False:
            group_visibility = "direct messages only"
        elif bot["can_read_all_group_messages"] is True:
            group_visibility = "all group messages"
        elif bot["can_read_all_group_messages"] is False:
            group_visibility = "mentions only"
    return {
        "account_id": account.get("account_id"),
        "status": account.get("status"),
        "enabled": account.get("enabled"),
        "bot": bot,
        "webhook": webhook,
        "privacy_mode": privacy_mode,
        "group_visibility": group_visibility,
        "last_activity_at": _coalesce(
            account.get("last_activity_at"),
            account.get("last_message_at"),
            account.get("updated_at"),
        ),
        "messages_24h": _coalesce(
            messages_total,
            (messages_in or 0) + (messages_out or 0)
            if messages_in is not None or messages_out is not None
            else None,
        ),
        "messages_24h_in": messages_in,
        "messages_24h_out": messages_out,
        "chats_24h": _coalesce(
            account.get("chats_24h"), account.get("active_chats_24h")
        ),
        "forward_failures": _coalesce(
            account.get("forward_failures"),
            account.get("forward_failures_24h"),
        ),
        "error": _coalesce(account.get("error"), webhook.get("last_error")),
    }


def _sum_accounts(accounts: list[dict], key: str):
    values = [account.get(key) for account in accounts]
    present = [value for value in values if isinstance(value, (int, float))]
    return sum(present) if present else None


def normalize_stats(stats: dict) -> dict:
    """Normalize canonical v0.2 stats and the gateway's flat transition shape."""
    accounts = [
        normalize_account(account)
        for account in (stats.get("accounts") or [])
        if isinstance(account, dict)
    ]
    totals = stats.get("totals") if isinstance(stats.get("totals"), dict) else {}
    db = stats.get("db")
    if not isinstance(db, dict):
        db = stats.get("database") if isinstance(stats.get("database"), dict) else {}
    if not db:
        db = {
            "ok": _coalesce(stats.get("db_ok"), stats.get("database_ok")),
            "latency_ms": _coalesce(
                stats.get("db_latency_ms"), stats.get("database_latency_ms")
            ),
            "error": _coalesce(stats.get("db_error"), stats.get("database_error")),
        }

    messages_total = _coalesce(
        totals.get("messages_24h"),
        stats.get("messages_24h"),
        _sum_accounts(accounts, "messages_24h"),
    )
    messages_in = _coalesce(
        totals.get("messages_24h_in"),
        stats.get("messages_24h_in"),
        _sum_accounts(accounts, "messages_24h_in"),
        messages_total,
    )
    messages_out = _coalesce(
        totals.get("messages_24h_out"),
        stats.get("messages_24h_out"),
        _sum_accounts(accounts, "messages_24h_out"),
        0 if messages_total is not None else None,
    )
    hourly = []
    for bucket in stats.get("hourly") or stats.get("message_hourly") or []:
        if not isinstance(bucket, dict):
            continue
        hourly.append(
            {
                "hour": _coalesce(
                    bucket.get("hour"),
                    bucket.get("timestamp"),
                    bucket.get("bucket"),
                ),
                "in": _coalesce(
                    bucket.get("in"), bucket.get("messages_in"), 0
                ),
                "out": _coalesce(
                    bucket.get("out"), bucket.get("messages_out"), 0
                ),
            }
        )
    return {
        "status": stats.get("status"),
        "version": _coalesce(stats.get("version"), stats.get("gateway_version")),
        "uptime_s": _coalesce(
            stats.get("uptime_s"), stats.get("uptime_seconds")
        ),
        "db": db,
        "webhook": normalize_webhook(stats.get("webhook"), stats),
        "totals": {
            "accounts": _coalesce(
                totals.get("accounts"),
                stats.get("accounts_count"),
                stats.get("account_count"),
                len(accounts),
            ),
            "active_chats": _coalesce(
                totals.get("active_chats"),
                totals.get("chats_24h"),
                stats.get("chats_24h"),
                _sum_accounts(accounts, "chats_24h"),
            ),
            "messages_24h": messages_total,
            "messages_24h_in": messages_in,
            "messages_24h_out": messages_out,
            "forward_failures_24h": _coalesce(
                totals.get("forward_failures_24h"),
                totals.get("forward_failures"),
                stats.get("forward_failures_24h"),
                stats.get("forward_failures"),
                _sum_accounts(accounts, "forward_failures"),
            ),
        },
        "hourly": hourly,
        "accounts": accounts,
    }


def gateway_config() -> tuple[str, str]:
    settings = config.get_settings()
    return (
        settings.telegram_gateway_url.rstrip("/"),
        settings.telegram_gateway_admin_key,
    )


def relay_inbound_url(agent_slug: str) -> str:
    base = config.get_settings().base_url.rstrip("/")
    return f"{base}/api/webhooks/telegram/{agent_slug}/inbound"


async def _gateway(
    method: str, path: str, json_body: dict | None = None
) -> httpx.Response:
    url, admin_key = gateway_config()
    if not url:
        raise RuntimeError("telegram gateway not configured")
    async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT_S) as client:
        return await client.request(
            method,
            f"{url}{path}",
            headers={"x-admin-key": admin_key},
            json=json_body,
        )


async def disconnect_agent(agent: Agent) -> dict:
    response = await _gateway("DELETE", f"/accounts/{agent.slug}")
    return {
        "deleted": response.status_code in (200, 204, 404),
        "status_code": response.status_code,
    }


async def seed_supported_plugin(db: AsyncSession) -> None:
    """Advertise Telegram only when an actual marketplace URL is configured."""
    marketplace_url = config.get_settings().telegram_plugin_marketplace_url.strip()
    if not marketplace_url:
        return
    existing = (
        await db.execute(
            select(PluginCatalogEntry).where(
                PluginCatalogEntry.plugin_name == PLUGIN_NAME
            )
        )
    ).scalar_one_or_none()
    if existing:
        return
    db.add(
        PluginCatalogEntry(
            plugin_name=PLUGIN_NAME,
            display_name="Telegram",
            marketplace_url=marketplace_url,
            category="Messaging",
            tier="supported",
            service_slug=None,
            key_mode="proxy",
            suggested=None,
            enabled=True,
        )
    )
