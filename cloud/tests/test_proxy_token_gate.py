"""Plan 077 — token-gated HTTP pass-through for the playbook delegation card.

The card polls from an opaque-origin srcdoc iframe (no session cookie); the
proxy forwards that one GET by slug and the tenant's per-delegation capability
token is the auth. Everything else keeps requiring a session.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.responses import Response
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

CARD_PATH = "api/p/plugin-playbooks/delegations/af200532-1111-2222-3333-444444444444/card"


class TestTokenGatedCardProxy:
    async def test_card_get_forwarded_without_session(self, anon_client: AsyncClient, sample_agent):
        mock_resp = Response(
            content='{"status":"running"}', status_code=200, media_type="application/json",
        )
        with patch(
            "cloud.api.proxy._proxy_request", new_callable=AsyncMock, return_value=mock_resp,
        ) as mock_proxy:
            resp = await anon_client.get(f"/a/{sample_agent.slug}/{CARD_PATH}?token=abc")
        assert resp.status_code == 200
        assert resp.json() == {"status": "running"}
        # Forwarded sessionless: no user object reaches _proxy_request.
        assert mock_proxy.await_args.args[1] is None

    async def test_card_get_unknown_slug_404(self, anon_client: AsyncClient):
        resp = await anon_client.get(f"/a/no-such-agent/{CARD_PATH}?token=abc")
        assert resp.status_code == 404

    async def test_card_get_never_wakes_stopped_agent(
        self, anon_client: AsyncClient, sample_agent, db_session,
    ):
        sample_agent.status = "stopped"
        await db_session.commit()
        with patch("cloud.api.proxy._try_wake_agent", new_callable=AsyncMock) as mock_wake:
            resp = await anon_client.get(f"/a/{sample_agent.slug}/{CARD_PATH}?token=abc")
        assert resp.status_code == 503
        mock_wake.assert_not_awaited()

    async def test_card_post_still_requires_session(self, anon_client: AsyncClient, sample_agent):
        resp = await anon_client.post(f"/a/{sample_agent.slug}/{CARD_PATH}")
        assert resp.status_code == 401

    async def test_other_paths_still_require_session(self, anon_client: AsyncClient, sample_agent):
        resp = await anon_client.get(f"/a/{sample_agent.slug}/api/health")
        assert resp.status_code == 401
        # Near-miss paths must not slip through the anchored regex.
        for path in (
            "api/p/plugin-playbooks/delegations/x/card/extra",
            "api/p/plugin-playbooks/delegations//card",
            "api/p/plugin-playbooks/delegations/x/card2",
        ):
            resp = await anon_client.get(f"/a/{sample_agent.slug}/{path}")
            assert resp.status_code == 401, path

    async def test_upstream_failure_maps_to_502(self, anon_client: AsyncClient, sample_agent):
        with patch(
            "cloud.api.proxy._proxy_request",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("boom"),
        ):
            resp = await anon_client.get(f"/a/{sample_agent.slug}/{CARD_PATH}?token=abc")
        assert resp.status_code == 502


class TestProxyRequestUserHeader:
    """_proxy_request only injects x-luna-user when a session user exists."""

    @staticmethod
    def _fake_request() -> "object":
        from starlette.requests import Request as StarletteRequest

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": f"/a/test/{CARD_PATH}",
            "raw_path": f"/a/test/{CARD_PATH}".encode(),
            "query_string": b"token=abc",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("127.0.0.1", 1234),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        return StarletteRequest(scope, receive)

    async def _captured_headers(self, user, sample_agent) -> dict:
        from cloud.api import proxy as proxy_mod

        captured: dict = {}

        class _Stop(Exception):
            pass

        class FakeClient:
            def build_request(self, method, url, headers, content):
                captured.update(headers)
                raise _Stop

        with patch.object(proxy_mod, "_get_http_client", return_value=FakeClient()):
            with pytest.raises(_Stop):
                await proxy_mod._proxy_request(
                    self._fake_request(), user, sample_agent, sample_agent.slug, CARD_PATH,
                )
        return captured

    async def test_sessionless_omits_user_header(self, sample_agent):
        headers = await self._captured_headers(None, sample_agent)
        assert "x-luna-user" not in headers
        assert "x-luna-proxy-secret" in headers

    async def test_session_user_keeps_user_header(self, sample_agent, admin_user):
        headers = await self._captured_headers(admin_user, sample_agent)
        assert headers["x-luna-user"] == admin_user.email
        assert "x-luna-proxy-secret" in headers
