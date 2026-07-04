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
VAULT_SECRET_KEY = "plugin_whatsapp.shared_secret"
VAULT_ACCOUNT_ID_KEY = "plugin_whatsapp.account_id"


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


async def connect_agent(agent: Agent, *, admin_email: str) -> dict:
    """Create the gateway account for this agent and wire the plugin.

    Idempotent. Returns a summary dict; raises only on gateway-unreachable /
    gateway-error (callers map to HTTP errors).
    """
    from cloud.api.agent_routes import _tenant_request

    resp = await _gateway("POST", "/accounts", {
        "account_id": agent.slug,
        "inbound_url": relay_inbound_url(agent.slug),
    })
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"gateway /accounts failed: {resp.status_code} {resp.text[:200]}")
    account = resp.json()
    secret = account.get("secret")

    result = {
        "account_id": account.get("account_id", agent.slug),
        "account_status": account.get("status"),
        "secret_stored": False,
        "account_id_stored": False,
        "plugin_installed": False,
    }

    # Vault writes over the trusted proxy — restart-free. The secret is only
    # returned on create/rotate; on an idempotent re-connect it is absent and
    # the existing vault value stays valid.
    if secret:
        code, _ = await _tenant_request(
            agent, "POST", "/api/p/plugin-vault/credentials",
            {"name": VAULT_SECRET_KEY, "value": secret, "kind": "api_key"},
            user_email=admin_email,
        )
        result["secret_stored"] = code == 200
        if code != 200:
            log.error("whatsapp.connect vault secret write failed agent=%s code=%s",
                      agent.slug, code)
    code, _ = await _tenant_request(
        agent, "POST", "/api/p/plugin-vault/credentials",
        {"name": VAULT_ACCOUNT_ID_KEY, "value": agent.slug, "kind": "api_key"},
        user_email=admin_email,
    )
    result["account_id_stored"] = code == 200

    # Plugin code (live-load, restart-free). Best-effort + idempotent.
    s = config.get_settings()
    code, _ = await _tenant_request(
        agent, "POST", "/api/p/plugin-marketplace/install",
        {"marketplace_url": s.whatsapp_plugin_marketplace_url, "name": PLUGIN_NAME},
        user_email=admin_email, timeout=60.0,
    )
    result["plugin_installed"] = code == 200

    return result


async def disconnect_agent(agent: Agent) -> dict:
    resp = await _gateway("DELETE", f"/accounts/{agent.slug}")
    return {"deleted": resp.status_code in (200, 204), "status_code": resp.status_code}


async def fetch_account_qr(agent_slug: str, fmt: str = "html") -> httpx.Response:
    return await _gateway("GET", f"/accounts/{agent_slug}/qr?format={fmt}")
