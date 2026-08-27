"""Plan 076 — generic webhook gateway: mint API + public ingress."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from cloud.db.models import RelayDelivery, WebhookEndpoint
from cloud.gateway.tokens import issue_token
from cloud.relay import standard_webhooks as sw


async def _token(db_session, agent):
    # issue_token only flushes; commit so the app's sessions (sharing the
    # in-memory SQLite connection) can't roll the token away on close.
    tok = await issue_token(db_session, agent.id)
    await db_session.commit()
    return tok


async def _mint(anon_client, db_session, agent, **overrides):
    tok = await _token(db_session, agent)
    payload = {
        "name": "test-hook",
        "plugin": "plugin-webhooks",
        "target_path": "/api/p/plugin-webhooks/hooks/inbound",
        **overrides,
    }
    res = await anon_client.post(
        "/api/agent/webhooks/hooks",
        json=payload,
        headers={"Authorization": f"Bearer {tok}"},
    )
    return res


# ── Mint API ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestMint:
    async def test_create_returns_secret_and_url(self, anon_client, db_session, sample_agent):
        res = await _mint(anon_client, db_session, sample_agent)
        assert res.status_code == 200
        body = res.json()
        assert body["created"] is True
        assert body["secret"]
        assert body["public_url"].endswith(
            f"/api/webhooks/hooks/{sample_agent.slug}/{body['hook_slug']}"
        )
        assert body["mode"] == "sync"

    async def test_idempotent_recreate_no_secret(self, anon_client, db_session, sample_agent):
        await _mint(anon_client, db_session, sample_agent)
        res = await _mint(anon_client, db_session, sample_agent)
        assert res.status_code == 200
        body = res.json()
        assert body["created"] is False
        assert "secret" not in body

    async def test_rotate_recovers_secret(self, anon_client, db_session, sample_agent):
        first = (await _mint(anon_client, db_session, sample_agent)).json()
        rotated = (await _mint(anon_client, db_session, sample_agent, rotate=True)).json()
        assert rotated["secret"] and rotated["secret"] != first["secret"]
        assert rotated["hook_slug"] == first["hook_slug"]

    async def test_target_path_must_be_plugin_route(self, anon_client, db_session, sample_agent):
        res = await _mint(anon_client, db_session, sample_agent, target_path="/api/admin/x")
        assert res.status_code == 422

    async def test_bad_mode_rejected(self, anon_client, db_session, sample_agent):
        res = await _mint(anon_client, db_session, sample_agent, mode="fanout")
        assert res.status_code == 422

    async def test_requires_token(self, anon_client):
        res = await anon_client.post("/api/agent/webhooks/hooks", json={"name": "x"})
        assert res.status_code == 401

    async def test_list_patch_delete(self, anon_client, db_session, sample_agent):
        created = (await _mint(anon_client, db_session, sample_agent)).json()
        # issue_token rotates: mint first, then take the token used afterwards
        tok = await _token(db_session, sample_agent)
        hdrs = {"Authorization": f"Bearer {tok}"}

        listing = (await anon_client.get("/api/agent/webhooks/hooks", headers=hdrs)).json()
        assert [h["hook_slug"] for h in listing["hooks"]] == [created["hook_slug"]]
        assert all("secret" not in h for h in listing["hooks"])

        res = await anon_client.patch(
            f"/api/agent/webhooks/hooks/{created['hook_slug']}",
            json={"enabled": False}, headers=hdrs)
        assert res.json()["enabled"] is False

        res = await anon_client.delete(
            f"/api/agent/webhooks/hooks/{created['hook_slug']}", headers=hdrs)
        assert res.json()["ok"] is True
        listing = (await anon_client.get("/api/agent/webhooks/hooks", headers=hdrs)).json()
        assert listing["hooks"] == []

    async def test_records_plugin_membership(self, anon_client, db_session, sample_agent):
        await _mint(anon_client, db_session, sample_agent, plugin="plugin-monday")
        await db_session.refresh(sample_agent)
        assert "plugin-monday" in (sample_agent.config_overrides or {}).get("installed_plugins", [])

    async def test_proxy_prefix_reachable(self, anon_client, db_session, sample_agent):
        tok = await _token(db_session, sample_agent)
        res = await anon_client.get(
            "/proxy/api/agent/webhooks/hooks",
            headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 200


# ── Public ingress ───────────────────────────────────────────────────────────

class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient inside webhook_routes."""

    def __init__(self, respond):
        self._respond = respond
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, content=None, headers=None):
        self.calls.append((method, url, content, headers))
        result = self._respond(url)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(
            result, request=httpx.Request(method, url), json={"ok": True}
        )

    async def get(self, url, headers=None, timeout=None):
        return httpx.Response(200, request=httpx.Request("GET", url))


def _patch_client(respond):
    fake = _FakeAsyncClient(respond)
    return fake, patch("cloud.api.webhook_routes.httpx.AsyncClient", return_value=fake)


@pytest.mark.asyncio
class TestIngress:
    async def _hook(self, anon_client, db_session, agent, **overrides):
        body = (await _mint(anon_client, db_session, agent, **overrides)).json()
        agent.internal_url = "http://machine.internal:8080"
        agent.runtime_ref = "mach-1"
        await db_session.commit()
        return body

    async def test_unknown_hook_404(self, anon_client, db_session, sample_agent):
        res = await anon_client.post(
            f"/api/webhooks/hooks/{sample_agent.slug}/nope", content=b"{}")
        assert res.status_code == 404

    async def test_disabled_hook_410(self, anon_client, db_session, sample_agent):
        hook = await self._hook(anon_client, db_session, sample_agent)
        tok = await _token(db_session, sample_agent)
        await anon_client.patch(
            f"/api/agent/webhooks/hooks/{hook['hook_slug']}",
            json={"enabled": False},
            headers={"Authorization": f"Bearer {tok}"})
        res = await anon_client.post(
            f"/api/webhooks/hooks/{sample_agent.slug}/{hook['hook_slug']}", content=b"{}")
        assert res.status_code == 410

    async def test_oversize_413(self, anon_client, db_session, sample_agent):
        hook = await self._hook(anon_client, db_session, sample_agent)
        res = await anon_client.post(
            f"/api/webhooks/hooks/{sample_agent.slug}/{hook['hook_slug']}",
            content=b"x" * (200 * 1024 + 1))
        assert res.status_code == 413

    async def test_sync_forwards_with_verifiable_signature(
        self, anon_client, db_session, sample_agent
    ):
        hook = await self._hook(anon_client, db_session, sample_agent)
        body = b'{"event": "ping"}'
        fake, patcher = _patch_client(lambda url: 200)
        with patcher:
            res = await anon_client.post(
                f"/api/webhooks/hooks/{sample_agent.slug}/{hook['hook_slug']}?a=1",
                content=body,
                headers={"x-provider-sig": "keepme", "authorization": "Bearer dropme"})
        assert res.status_code == 200

        method, url, content, headers = fake.calls[0]
        assert method == "POST"
        assert url == "http://machine.internal:8080/api/p/plugin-webhooks/hooks/inbound?a=1"
        assert content == body
        # provider headers pass through; sensitive ones are dropped
        assert headers["x-provider-sig"] == "keepme"
        assert "authorization" not in headers
        assert headers["fly-force-instance-id"] == "mach-1"
        assert headers["x-luna-hook-name"] == "test-hook"
        assert headers["x-luna-proxy-secret"]
        # the plugin can verify with the per-hook secret
        sw.verify(
            secret=hook["secret"],
            webhook_id=headers["webhook-id"],
            timestamp=headers["webhook-timestamp"],
            raw_body=content,
            signature_header=headers["webhook-signature"],
        )

    async def test_sync_get_forwarded(self, anon_client, db_session, sample_agent):
        hook = await self._hook(anon_client, db_session, sample_agent)
        fake, patcher = _patch_client(lambda url: 200)
        with patcher:
            res = await anon_client.get(
                f"/api/webhooks/hooks/{sample_agent.slug}/{hook['hook_slug']}?challenge=abc")
        assert res.status_code == 200
        method, url, _, _ = fake.calls[0]
        assert method == "GET" and url.endswith("?challenge=abc")

    async def test_sync_drops_accept_encoding(self, anon_client, db_session, sample_agent):
        # Fly's edge compresses per accept-encoding, and httpx here may not be
        # able to decode what the caller accepts (br) — the echo would come
        # back as raw brotli labeled application/json. Never forward it.
        hook = await self._hook(anon_client, db_session, sample_agent)
        fake, patcher = _patch_client(lambda url: 200)
        with patcher:
            res = await anon_client.post(
                f"/api/webhooks/hooks/{sample_agent.slug}/{hook['hook_slug']}",
                content=b"{}",
                headers={"accept-encoding": "br"})
        assert res.status_code == 200
        _, _, _, headers = fake.calls[0]
        assert "accept-encoding" not in headers

    async def test_sync_wake_retry_once(self, anon_client, db_session, sample_agent):
        hook = await self._hook(anon_client, db_session, sample_agent)
        attempts = []

        def respond(url):
            attempts.append(url)
            if len(attempts) == 1:
                return httpx.ConnectError("asleep")
            return 200

        fake, patcher = _patch_client(respond)
        wake = AsyncMock(return_value=True)
        with patcher, patch("cloud.api.proxy._try_wake_agent", wake):
            res = await anon_client.post(
                f"/api/webhooks/hooks/{sample_agent.slug}/{hook['hook_slug']}", content=b"{}")
        assert res.status_code == 200
        assert wake.await_count == 1
        assert len(attempts) == 2

    async def test_sync_wake_failure_502(self, anon_client, db_session, sample_agent):
        hook = await self._hook(anon_client, db_session, sample_agent)
        fake, patcher = _patch_client(lambda url: httpx.ConnectError("dead"))
        with patcher, patch("cloud.api.proxy._try_wake_agent", AsyncMock(return_value=False)):
            res = await anon_client.post(
                f"/api/webhooks/hooks/{sample_agent.slug}/{hook['hook_slug']}", content=b"{}")
        assert res.status_code == 502

    async def test_queue_mode_enqueues_envelope(self, anon_client, db_session, sample_agent):
        hook = await self._hook(anon_client, db_session, sample_agent, mode="queue")
        body = b'{"n": 1}'
        res = await anon_client.post(
            f"/api/webhooks/hooks/{sample_agent.slug}/{hook['hook_slug']}", content=body)
        assert res.status_code == 202

        db_session.expire_all()
        row = (await db_session.execute(select(RelayDelivery))).scalars().one()
        assert row.status == "pending"
        assert row.target_path == "/api/p/plugin-webhooks/hooks/inbound"
        env = json.loads(row.body)
        assert env["hook"] == "test-hook" and env["body"] == '{"n": 1}'
        expected = hmac_mod.new(hook["secret"].encode(), body, hashlib.sha256).hexdigest()
        assert env["signature"] == expected

    async def test_stats_bumped(self, anon_client, db_session, sample_agent):
        hook = await self._hook(anon_client, db_session, sample_agent)
        fake, patcher = _patch_client(lambda url: 200)
        with patcher:
            await anon_client.post(
                f"/api/webhooks/hooks/{sample_agent.slug}/{hook['hook_slug']}", content=b"{}")
        db_session.expire_all()
        ep = (await db_session.execute(select(WebhookEndpoint))).scalars().one()
        assert ep.delivery_count == 1 and ep.last_status_code == 200 and ep.last_delivery_at
