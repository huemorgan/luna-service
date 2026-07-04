"""Per-instance WhatsApp connect flow (plan 034 Phase 2).

One gateway account = one WhatsApp number = one Luna. Connect is restart-free:
the per-account secret and account id go to the tenant's vault
(``plugin_whatsapp.shared_secret`` / ``plugin_whatsapp.account_id``, both read
vault-first by plugin-whatsapp >= 0.6.0); only ``LUNA_WHATSAPP_GATEWAY_URL``
is env, baked into new images and pushed once to older machines.

Inbound is a direct signed POST from the gateway. Tenant Fly machines need the
``fly-force-instance-id`` header and may be asleep, so accounts register OUR
public relay (``/api/webhooks/whatsapp/{slug}/inbound``) as their inbound URL;
the relay forwards the raw envelope to the machine (wake + retry) and the
plugin verifies the HMAC itself.
"""

from __future__ import annotations

import logging

import httpx

from cloud import config
from cloud.db.models import Agent

log = logging.getLogger(__name__)

GATEWAY_TIMEOUT_S = 10.0
PLUGIN_NAME = "plugin-whatsapp"


def gateway_config() -> tuple[str, str]:
    s = config.get_settings()
    return s.whatsapp_gateway_url.rstrip("/"), s.whatsapp_gateway_admin_key


def relay_inbound_url(agent_slug: str) -> str:
    base = config.get_settings().base_url.rstrip("/")
    return f"{base}/api/webhooks/whatsapp/{agent_slug}/inbound"


async def _gateway(method: str, path: str, json_body: dict | None = None) -> httpx.Response:
    url, admin_key = gateway_config()
    if not url:
        raise RuntimeError("whatsapp gateway not configured")
    async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT_S) as client:
        return await client.request(
            method, f"{url}{path}", headers={"x-admin-key": admin_key}, json=json_body
        )


async def disconnect_agent(agent: Agent) -> dict:
    resp = await _gateway("DELETE", f"/accounts/{agent.slug}")
    return {"deleted": resp.status_code in (200, 204), "status_code": resp.status_code}


async def fetch_account_qr(agent_slug: str, fmt: str = "html") -> httpx.Response:
    return await _gateway("GET", f"/accounts/{agent_slug}/qr?format={fmt}")
