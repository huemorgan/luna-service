"""Plan 052 §2 — plugin-catalog install hook: proxy-login JWT exchange.

Agent core rejects proxy-secret-only auth for writes, so the marketplace
install POST must first exchange the proxy headers for a JWT via
``POST /api/auth/proxy-login``. These tests run a mock machine that 401s
writes without a Bearer token and 200s with it.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from cloud.api.agent_routes import _tenant_request
from cloud.api.gateway_env_delta import apply_gateway_env_delta
from cloud.db.models import PluginCatalogEntry

pytestmark = pytest.mark.asyncio

TOKEN = "jwt-tok-123"


class MockMachine:
    """Mock tenant machine: proxy-login mints a JWT; writes require it."""

    def __init__(self, *, login_status: int = 200):
        self.login_status = login_status
        self.login_calls = 0
        self.install_calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/proxy-login":
            self.login_calls += 1
            if request.headers.get("x-luna-proxy-secret") is None:
                return httpx.Response(401, json={"detail": "no proxy secret"})
            if self.login_status != 200:
                return httpx.Response(self.login_status, json={"detail": "login refused"})
            return httpx.Response(200, json={"access_token": TOKEN, "token_type": "bearer"})
        if request.url.path == "/api/p/plugin-marketplace/install":
            self.install_calls.append(request)
            if request.headers.get("authorization") != f"Bearer {TOKEN}":
                return httpx.Response(401, json={"detail": "write requires JWT"})
            return httpx.Response(200, json={"ok": True, "name": json.loads(request.content)["name"]})
        return httpx.Response(404, json={"detail": "unknown path"})

    def patch_client(self):
        real = httpx.AsyncClient
        transport = httpx.MockTransport(self.handler)

        def factory(**kw):
            kw["transport"] = transport
            return real(**kw)

        return patch("cloud.api.agent_routes.httpx.AsyncClient", factory)


# ── _tenant_request auth modes ───────────────────────────────────────────────

async def test_jwt_auth_exchanges_then_bears_token(sample_agent):
    machine = MockMachine()
    with machine.patch_client():
        code, data = await _tenant_request(
            sample_agent, "POST", "/api/p/plugin-marketplace/install",
            {"marketplace_url": "http://mp.test", "name": "plugin-x"},
            user_email="vaselin@gmail.com", auth="jwt",
        )
    assert code == 200 and data["ok"] is True
    assert machine.login_calls == 1
    assert len(machine.install_calls) == 1
    req = machine.install_calls[0]
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert req.headers["x-luna-proxy-secret"]  # proxy headers still present
    assert req.headers["x-luna-user"] == "vaselin@gmail.com"


async def test_proxy_auth_skips_login_and_write_401s(sample_agent):
    machine = MockMachine()
    with machine.patch_client():
        code, _ = await _tenant_request(
            sample_agent, "POST", "/api/p/plugin-marketplace/install",
            {"marketplace_url": "http://mp.test", "name": "plugin-x"},
            user_email="vaselin@gmail.com",
        )
    assert code == 401  # default proxy auth is not enough for writes
    assert machine.login_calls == 0


async def test_jwt_login_failure_short_circuits(sample_agent):
    machine = MockMachine(login_status=503)
    with machine.patch_client():
        code, data = await _tenant_request(
            sample_agent, "POST", "/api/p/plugin-marketplace/install", {},
            user_email="vaselin@gmail.com", auth="jwt",
        )
    assert code == 503
    assert data == {"error": "proxy-login failed"}
    assert machine.install_calls == []  # never attempted the write


# ── apply_gateway_env_delta uses the exchange ────────────────────────────────

async def test_env_delta_installs_with_jwt(_patch_db, sample_agent):
    machine = MockMachine()
    with machine.patch_client():
        result = await apply_gateway_env_delta(
            sample_agent.id, marketplace_url="http://mp.test",
            plugin_name="plugin-x", admin_email="vaselin@gmail.com",
        )
    assert result["plugin_installed"] is True
    assert machine.login_calls == 1
    # no FLY_API_TOKEN in test env → env push is skipped, not failed
    assert result["note"] in ("fly_not_configured", None)


# ── admin route end-to-end ───────────────────────────────────────────────────

async def test_install_route_reports_plugin_installed(admin_client, db_session, sample_agent):
    db_session.add(PluginCatalogEntry(
        plugin_name="plugin-x", display_name="X", tier="default",
        service_slug=None, key_mode="proxy", enabled=True,
        marketplace_url="http://mp.test",
    ))
    await db_session.commit()

    machine = MockMachine()
    with machine.patch_client():
        resp = await admin_client.post(
            "/api/admin/plugin-catalog/install",
            json={"agent_id": str(sample_agent.id), "plugin_name": "plugin-x"},
            headers={"Origin": "http://test"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["plugin_installed"] is True
    assert machine.login_calls == 1
    assert len(machine.install_calls) == 1
