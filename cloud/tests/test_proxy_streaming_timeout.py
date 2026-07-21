"""045/phase06 (= 044 Bug 6) — streaming-aware proxy timeouts.

Slow hosted turns died as httpcore.ReadTimeout raised through the ASGI stack
(415/8 h storms in the Render logs). SSE requests now get a longer per-chunk
idle read allowance, and the proxy's stream generator ends cleanly on a
stalled upstream or a client abort — upstream response always closed, no
exception through ASGI.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from starlette.requests import Request

from cloud.api.proxy import _proxy_request, _stream_idle_read_seconds

pytestmark = pytest.mark.asyncio


class FakeStreamResp:
    """Minimal httpx streaming-response stand-in."""

    def __init__(self, chunks, exc=None, status=200, content_type="text/event-stream"):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.closed = False
        self._chunks = chunks
        self._exc = exc

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c
        if self._exc is not None:
            raise self._exc

    async def aread(self):
        return b"".join(self._chunks)

    async def aclose(self):
        self.closed = True


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.last_req = None

    def build_request(self, method, url, headers=None, content=None):
        self.last_req = httpx.Request(method, url, headers=headers, content=content)
        return self.last_req

    async def send(self, req, stream=True):
        return self.resp


def _make_request(accept: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/events",
        "query_string": b"",
        "headers": [(b"accept", accept.encode())],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _fake_agent():
    agent = MagicMock()
    agent.id = "00000000-0000-0000-0000-000000000001"
    agent.internal_url = "http://agent.internal:8765"
    agent.runtime_ref = None
    return agent


def _fake_user():
    user = MagicMock()
    user.email = "owner@example.com"
    return user


class TestStreamIdleRead:
    async def test_default_and_env_override(self, monkeypatch):
        monkeypatch.delenv("PROXY_STREAM_IDLE_READ", raising=False)
        assert _stream_idle_read_seconds() == 300.0
        monkeypatch.setenv("PROXY_STREAM_IDLE_READ", "600")
        assert _stream_idle_read_seconds() == 600.0
        monkeypatch.setenv("PROXY_STREAM_IDLE_READ", "garbage")
        assert _stream_idle_read_seconds() == 300.0


class TestStreamingTimeout:
    async def test_sse_request_gets_long_idle_read(self):
        fake = FakeClient(FakeStreamResp([b"data: hi\n\n"]))
        with patch("cloud.api.proxy._get_http_client", return_value=fake):
            resp = await _proxy_request(
                _make_request("text/event-stream"), _fake_user(), _fake_agent(), "luna", "api/events",
            )
            body = b"".join([c async for c in resp.body_iterator])
        assert body == b"data: hi\n\n"
        timeout = fake.last_req.extensions.get("timeout")
        assert timeout is not None
        assert timeout["read"] == 300.0
        assert fake.resp.closed

    async def test_non_sse_request_keeps_default_timeout(self):
        fake = FakeClient(FakeStreamResp([b"{}"], content_type="application/json"))
        with patch("cloud.api.proxy._get_http_client", return_value=fake):
            resp = await _proxy_request(
                _make_request("application/json"), _fake_user(), _fake_agent(), "luna", "api/health",
            )
            b"".join([c async for c in resp.body_iterator])
        assert "timeout" not in fake.last_req.extensions

    async def test_stalled_upstream_closes_cleanly(self):
        """ReadTimeout mid-stream: chunks so far delivered, stream ends, no raise."""
        fake = FakeClient(FakeStreamResp([b"data: a\n\n"], exc=httpx.ReadTimeout("idle")))
        with patch("cloud.api.proxy._get_http_client", return_value=fake):
            resp = await _proxy_request(
                _make_request("text/event-stream"), _fake_user(), _fake_agent(), "luna", "api/events",
            )
            body = b"".join([c async for c in resp.body_iterator])  # must NOT raise
        assert body == b"data: a\n\n"
        assert fake.resp.closed

    async def test_broken_upstream_closes_cleanly(self):
        fake = FakeClient(FakeStreamResp([b"x"], exc=httpx.ReadError("reset")))
        with patch("cloud.api.proxy._get_http_client", return_value=fake):
            resp = await _proxy_request(
                _make_request("text/event-stream"), _fake_user(), _fake_agent(), "luna", "api/events",
            )
            body = b"".join([c async for c in resp.body_iterator])
        assert body == b"x"
        assert fake.resp.closed

    async def test_client_disconnect_closes_upstream(self):
        """Aborting the generator mid-stream still closes the upstream response."""
        fake = FakeClient(FakeStreamResp([b"one", b"two", b"three"]))
        with patch("cloud.api.proxy._get_http_client", return_value=fake):
            resp = await _proxy_request(
                _make_request("text/event-stream"), _fake_user(), _fake_agent(), "luna", "api/events",
            )
            gen = resp.body_iterator
            assert await gen.__anext__() == b"one"
            await gen.aclose()  # simulates the client going away
        assert fake.resp.closed


class TestProxiedThroughApp:
    async def test_sse_via_full_route(self, admin_client: AsyncClient, sample_agent):
        """End-to-end through /a/{slug}/ routing with a fake upstream stream."""
        fake = FakeClient(FakeStreamResp([b"data: live\n\n"]))
        with patch("cloud.api.proxy._get_http_client", return_value=fake):
            resp = await admin_client.get(
                f"/a/{sample_agent.slug}/api/events", headers={"accept": "text/event-stream"},
            )
        assert resp.status_code == 200
        assert b"data: live" in resp.content
        assert fake.resp.closed
