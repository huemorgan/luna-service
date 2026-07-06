"""Per-instance scheduler connect flow (plan 035).

One scheduler-service account = one Luna. Connect is plugin-initiated and
restart-free: the per-account secret, account id, and service URL go to the
tenant's vault (read vault-first by plugin-scheduler); nothing is env.

Fires are signed POSTs from the service. Tenant Fly machines need the
``fly-force-instance-id`` header and may be asleep, so accounts register OUR
public relay (``/api/webhooks/scheduler/{slug}/fire``) as their fire URL; the
relay forwards the raw payload to the machine (wake + retry once) and the
plugin verifies the HMAC itself.
"""

from __future__ import annotations

import logging

import httpx

from cloud import config
from cloud.db.models import Agent

log = logging.getLogger(__name__)

SERVICE_TIMEOUT_S = 10.0
PLUGIN_NAME = "plugin-scheduler"


def service_config() -> tuple[str, str]:
    s = config.get_settings()
    return s.scheduler_service_url.rstrip("/"), s.scheduler_service_admin_key


def relay_fire_url(agent_slug: str) -> str:
    base = config.get_settings().base_url.rstrip("/")
    return f"{base}/api/webhooks/scheduler/{agent_slug}/fire"


async def _service(method: str, path: str, json_body: dict | None = None) -> httpx.Response:
    url, admin_key = service_config()
    if not url:
        raise RuntimeError("scheduler service not configured")
    async with httpx.AsyncClient(timeout=SERVICE_TIMEOUT_S) as client:
        return await client.request(
            method, f"{url}{path}", headers={"x-admin-key": admin_key}, json=json_body
        )


async def disconnect_agent(agent: Agent) -> dict:
    resp = await _service("DELETE", f"/accounts/{agent.slug}")
    return {"deleted": resp.status_code in (200, 204), "status_code": resp.status_code}
