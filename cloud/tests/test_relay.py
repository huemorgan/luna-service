"""Plan 015 — Composio trigger relay tests."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from cloud.db.models import Agent, ComposioAccountLink, RelayDelivery
from cloud.relay import standard_webhooks as sw
from cloud.relay.capture import extract_connected_accounts, extract_event_account
from cloud.relay.secrets import derive_relay_secret

SECRET = "test-composio-secret"


def _signed_headers(body: bytes, *, secret: str = SECRET, webhook_id: str | None = None, skew: int = 0):
    headers = sw.sign(
        secret=secret,
        webhook_id=webhook_id or f"msg_{uuid.uuid4().hex[:12]}",
        timestamp=int(time.time()) + skew,
        body=body,
    )
    headers["content-type"] = "application/json"
    return headers


def _event_body(connected_account: str = "ca_test_001") -> bytes:
    return json.dumps({
        "type": "gmail_new_gmail_message",
        "data": {"connected_account_id": connected_account, "app_name": "gmail"},
    }).encode()


# ── Standard Webhooks sign/verify ────────────────────────────────────────────

class TestStandardWebhooks:
    def test_sign_verify_roundtrip(self):
        body = b'{"hello": "world"}'
        h = sw.sign(secret=SECRET, webhook_id="msg_1", body=body)
        sw.verify(
            secret=SECRET, webhook_id="msg_1",
            timestamp=h["webhook-timestamp"], raw_body=body,
            signature_header=h["webhook-signature"],
        )

    def test_wrong_secret_rejected(self):
        body = b"{}"
        h = sw.sign(secret="other", webhook_id="msg_1", body=body)
        with pytest.raises(sw.WebhookAuthError):
            sw.verify(
                secret=SECRET, webhook_id="msg_1",
                timestamp=h["webhook-timestamp"], raw_body=body,
                signature_header=h["webhook-signature"],
            )

    def test_tampered_body_rejected(self):
        h = sw.sign(secret=SECRET, webhook_id="msg_1", body=b'{"a":1}')
        with pytest.raises(sw.WebhookAuthError):
            sw.verify(
                secret=SECRET, webhook_id="msg_1",
                timestamp=h["webhook-timestamp"], raw_body=b'{"a":2}',
                signature_header=h["webhook-signature"],
            )

    def test_expired_timestamp_rejected(self):
        body = b"{}"
        old = int(time.time()) - 600
        h = sw.sign(secret=SECRET, webhook_id="msg_1", timestamp=old, body=body)
        with pytest.raises(sw.WebhookAuthError, match="window"):
            sw.verify(
                secret=SECRET, webhook_id="msg_1",
                timestamp=str(old), raw_body=body,
                signature_header=h["webhook-signature"],
            )

    def test_future_timestamp_rejected(self):
        body = b"{}"
        future = int(time.time()) + 600
        h = sw.sign(secret=SECRET, webhook_id="msg_1", timestamp=future, body=body)
        with pytest.raises(sw.WebhookAuthError, match="window"):
            sw.verify(
                secret=SECRET, webhook_id="msg_1",
                timestamp=str(future), raw_body=body,
                signature_header=h["webhook-signature"],
            )

    def test_multi_signature_rotation(self):
        """Header carrying old+new signatures verifies against either secret."""
        body = b"{}"
        ts = int(time.time())
        old = sw.sign(secret="old-secret", webhook_id="m", timestamp=ts, body=body)
        new = sw.sign(secret="new-secret", webhook_id="m", timestamp=ts, body=body)
        combined = f"{old['webhook-signature']} {new['webhook-signature']}"
        for secret in ("old-secret", "new-secret"):
            sw.verify(
                secret=secret, webhook_id="m", timestamp=str(ts),
                raw_body=body, signature_header=combined,
            )

    def test_whsec_prefix_secret(self):
        import base64
        raw = b"0123456789abcdef0123456789abcdef"
        secret = "whsec_" + base64.b64encode(raw).decode()
        body = b"{}"
        h = sw.sign(secret=secret, webhook_id="m", body=body)
        sw.verify(
            secret=secret, webhook_id="m",
            timestamp=h["webhook-timestamp"], raw_body=body,
            signature_header=h["webhook-signature"],
        )

    def test_missing_headers_rejected(self):
        with pytest.raises(sw.WebhookAuthError, match="missing"):
            sw.verify(secret=SECRET, webhook_id="", timestamp="", raw_body=b"", signature_header="")


# ── Relay secret derivation ──────────────────────────────────────────────────

class TestRelaySecrets:
    def test_deterministic_and_distinct(self):
        a = derive_relay_secret("root", "agent-1")
        assert a == derive_relay_secret("root", "agent-1")
        assert a != derive_relay_secret("root", "agent-2")
        assert a != derive_relay_secret("other-root", "agent-1")

    def test_differs_from_proxy_secret(self):
        from cloud.runtime.proxy_secret import derive_proxy_secret
        assert derive_relay_secret("root", "agent-1") != derive_proxy_secret("root", "agent-1")


# ── Payload extraction ───────────────────────────────────────────────────────

class TestExtraction:
    def test_event_shapes(self):
        for payload in (
            {"data": {"connected_account_id": "ca_1"}},
            {"connectedAccountId": "ca_1"},
            {"payload": {"nested": {"connected_account_nano_id": "ca_1"}}},
        ):
            assert extract_event_account(payload) == "ca_1"

    def test_connected_accounts_listing_shape(self):
        payload = {
            "items": [
                {"id": "ca_a", "appUniqueId": "gmail", "status": "ACTIVE"},
                {"id": "ca_b", "toolkit": "slack", "status": "ACTIVE"},
            ]
        }
        accounts = extract_connected_accounts(payload)
        assert ("ca_a", "gmail") in accounts and ("ca_b", "slack") in accounts

    def test_plain_ids_not_captured(self):
        # Objects without account markers must not have their "id" harvested.
        assert extract_connected_accounts({"id": "trg_123", "name": "x"}) == []

    def test_no_match(self):
        assert extract_event_account({"data": {"foo": "bar"}}) is None


# ── Ingress route ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestIngress:
    async def _link(self, db_session, agent, account_id="ca_test_001"):
        db_session.add(ComposioAccountLink(
            connected_account_id=account_id, agent_id=agent.id, source="admin",
        ))
        await db_session.commit()

    async def test_no_secret_403(self, anon_client):
        with patch.dict("os.environ", {"CLOUD_COMPOSIO_WEBHOOK_SECRET": ""}):
            resp = await anon_client.post("/api/webhooks/composio", content=b"{}")
        assert resp.status_code == 403

    async def test_bad_signature_401_no_row(self, anon_client, db_session):
        body = _event_body()
        with patch.dict("os.environ", {"CLOUD_COMPOSIO_WEBHOOK_SECRET": SECRET}):
            resp = await anon_client.post(
                "/api/webhooks/composio", content=body,
                headers=_signed_headers(body, secret="wrong-secret"),
            )
        assert resp.status_code == 401
        rows = (await db_session.execute(select(RelayDelivery))).scalars().all()
        assert rows == []

    async def test_expired_timestamp_401(self, anon_client):
        body = _event_body()
        with patch.dict("os.environ", {"CLOUD_COMPOSIO_WEBHOOK_SECRET": SECRET}):
            resp = await anon_client.post(
                "/api/webhooks/composio", content=body,
                headers=_signed_headers(body, skew=-600),
            )
        assert resp.status_code == 401

    async def test_routable_event_202_pending(self, anon_client, db_session, sample_agent):
        await self._link(db_session, sample_agent)
        body = _event_body()
        with patch.dict("os.environ", {"CLOUD_COMPOSIO_WEBHOOK_SECRET": SECRET}):
            resp = await anon_client.post(
                "/api/webhooks/composio", content=body, headers=_signed_headers(body),
            )
        assert resp.status_code == 202
        assert resp.json()["status"] == "pending"
        row = (await db_session.execute(select(RelayDelivery))).scalar_one()
        assert row.agent_id == sample_agent.id
        assert row.connected_account_id == "ca_test_001"

    async def test_unroutable_event_kept(self, anon_client, db_session):
        body = _event_body("ca_unknown")
        with patch.dict("os.environ", {"CLOUD_COMPOSIO_WEBHOOK_SECRET": SECRET}):
            resp = await anon_client.post(
                "/api/webhooks/composio", content=body, headers=_signed_headers(body),
            )
        assert resp.status_code == 202
        assert resp.json()["status"] == "unroutable"
        row = (await db_session.execute(select(RelayDelivery))).scalar_one()
        assert row.status == "unroutable" and row.agent_id is None

    async def test_duplicate_webhook_id_deduped(self, anon_client, db_session, sample_agent):
        await self._link(db_session, sample_agent)
        body = _event_body()
        headers = _signed_headers(body, webhook_id="msg_dup_1")
        with patch.dict("os.environ", {"CLOUD_COMPOSIO_WEBHOOK_SECRET": SECRET}):
            first = await anon_client.post("/api/webhooks/composio", content=body, headers=headers)
            # Re-sign fresh (timestamp may differ) but keep the same webhook-id.
            second = await anon_client.post(
                "/api/webhooks/composio", content=body,
                headers=_signed_headers(body, webhook_id="msg_dup_1"),
            )
        assert first.status_code == 202 and second.status_code == 202
        assert second.json()["status"] == "duplicate"
        rows = (await db_session.execute(select(RelayDelivery))).scalars().all()
        assert len(rows) == 1

    async def test_oversize_body_413(self, anon_client):
        body = b"x" * (200 * 1024 + 1)
        with patch.dict("os.environ", {"CLOUD_COMPOSIO_WEBHOOK_SECRET": SECRET}):
            resp = await anon_client.post(
                "/api/webhooks/composio", content=body, headers=_signed_headers(body),
            )
        assert resp.status_code == 413


# ── Admin endpoints ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAdminRelay:
    async def test_links_crud(self, admin_client, db_session, sample_agent):
        create = await admin_client.post("/api/admin/relay/links", json={
            "connected_account_id": "ca_manual_1",
            "agent_slug": sample_agent.slug,
            "app_name": "gmail",
        })
        assert create.status_code == 201

        listing = await admin_client.get("/api/admin/relay/links")
        assert listing.status_code == 200
        accounts = [l["connected_account_id"] for l in listing.json()]
        assert "ca_manual_1" in accounts

        delete = await admin_client.delete("/api/admin/relay/links/ca_manual_1")
        assert delete.status_code == 200
        listing2 = await admin_client.get("/api/admin/relay/links")
        assert "ca_manual_1" not in [l["connected_account_id"] for l in listing2.json()]

    async def test_create_link_unknown_agent_404(self, admin_client):
        resp = await admin_client.post("/api/admin/relay/links", json={
            "connected_account_id": "ca_x", "agent_slug": "no-such-agent",
        })
        assert resp.status_code == 404

    async def test_deliveries_listing(self, admin_client, db_session, sample_agent):
        db_session.add(RelayDelivery(
            webhook_id="msg_list_1",
            connected_account_id="ca_test_001",
            agent_id=sample_agent.id,
            status="delivered",
            attempts=1,
            body="{}",
            delivered_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()
        resp = await admin_client.get("/api/admin/relay/deliveries")
        assert resp.status_code == 200
        rows = resp.json()
        assert rows and rows[0]["webhook_id"] == "msg_list_1"
        assert rows[0]["agent_slug"] == sample_agent.slug

    async def test_non_admin_403(self, regular_client):
        for path in ("/api/admin/relay/deliveries", "/api/admin/relay/links"):
            resp = await regular_client.get(path)
            assert resp.status_code == 403


# ── Forwarder state machine ──────────────────────────────────────────────────

@pytest.mark.asyncio
class TestForwarder:
    async def _pending(self, db_session, agent, **kw) -> RelayDelivery:
        d = RelayDelivery(
            webhook_id=kw.pop("webhook_id", f"msg_{uuid.uuid4().hex[:8]}"),
            connected_account_id="ca_test_001",
            agent_id=agent.id,
            status="pending",
            body=json.dumps({"data": {"connected_account_id": "ca_test_001"}}),
            **kw,
        )
        db_session.add(d)
        await db_session.commit()
        await db_session.refresh(d)
        return d

    async def _reload(self, db_session, delivery_id) -> RelayDelivery:
        db_session.expire_all()
        return (await db_session.execute(
            select(RelayDelivery).where(RelayDelivery.id == delivery_id)
        )).scalar_one()

    async def _run(self, db_session, delivery_id, respond):
        """Run deliver_one with a stubbed HTTP client."""
        import httpx
        from cloud.relay import forwarder

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def post(self, url, content=None, headers=None):
                self.calls.append((url, content, headers))
                result = respond(url)
                if isinstance(result, Exception):
                    raise result
                return httpx.Response(result, request=httpx.Request("POST", url))

        client = FakeClient()
        with patch.dict("os.environ", {"CLOUD_TRUSTED_PROXY_SECRET": "root"}):
            await forwarder.deliver_one(delivery_id, client)
        return client

    async def test_success_delivers_with_valid_signature(self, _patch_db, db_session, sample_agent):
        d = await self._pending(db_session, sample_agent)
        client = await self._run(db_session, d.id, lambda url: 200)

        url, content, headers = client.calls[0]
        assert url.endswith("/api/p/plugin-connectors/events/composio")
        assert headers["webhook-id"] == d.webhook_id
        # The receiving end (Luna) must be able to verify with the derived secret.
        sw.verify(
            secret=derive_relay_secret("root", str(sample_agent.id)),
            webhook_id=headers["webhook-id"],
            timestamp=headers["webhook-timestamp"],
            raw_body=content,
            signature_header=headers["webhook-signature"],
        )
        row = await self._reload(db_session, d.id)
        assert row.status == "delivered" and row.attempts == 1 and row.delivered_at

    async def test_custom_target_path_used(self, _patch_db, db_session, sample_agent):
        # Plan 076: a delivery with target_path set goes to that route.
        d = await self._pending(db_session, sample_agent, target_path="/api/p/plugin-webhooks/hooks/abc123")
        client = await self._run(db_session, d.id, lambda url: 200)
        url, _, _ = client.calls[0]
        assert url.endswith("/api/p/plugin-webhooks/hooks/abc123")
        row = await self._reload(db_session, d.id)
        assert row.status == "delivered"

    async def test_null_target_path_falls_back_to_composio(self, _patch_db, db_session, sample_agent):
        d = await self._pending(db_session, sample_agent)  # target_path NULL
        client = await self._run(db_session, d.id, lambda url: 200)
        assert client.calls[0][0].endswith("/api/p/plugin-connectors/events/composio")

    async def test_connection_error_backs_off(self, _patch_db, db_session, sample_agent):
        import httpx
        d = await self._pending(db_session, sample_agent)
        await self._run(db_session, d.id, lambda url: httpx.ConnectError("boom"))
        row = await self._reload(db_session, d.id)
        assert row.status == "pending" and row.attempts == 1
        assert row.next_attempt_at is not None
        next_at = row.next_attempt_at
        if next_at.tzinfo is None:  # SQLite returns naive datetimes
            next_at = next_at.replace(tzinfo=timezone.utc)
        assert next_at > datetime.now(timezone.utc) + timedelta(seconds=20)

    async def test_4xx_dead_letters_immediately(self, _patch_db, db_session, sample_agent):
        d = await self._pending(db_session, sample_agent)
        await self._run(db_session, d.id, lambda url: 401)
        row = await self._reload(db_session, d.id)
        assert row.status == "dead" and "401" in (row.last_error or "")

    async def test_max_attempts_dead_letters(self, _patch_db, db_session, sample_agent):
        import httpx
        from cloud.relay.forwarder import MAX_ATTEMPTS
        d = await self._pending(db_session, sample_agent, attempts=MAX_ATTEMPTS - 1)
        await self._run(db_session, d.id, lambda url: httpx.ConnectError("still down"))
        row = await self._reload(db_session, d.id)
        assert row.status == "dead" and row.attempts == MAX_ATTEMPTS

    async def test_agent_missing_dead_letters(self, _patch_db, db_session, sample_agent):
        d = await self._pending(db_session, sample_agent)
        # Simulate agent losing its runtime URL.
        agent = (await db_session.execute(
            select(Agent).where(Agent.id == sample_agent.id)
        )).scalar_one()
        agent.internal_url = None
        await db_session.commit()
        await self._run(db_session, d.id, lambda url: 200)
        row = await self._reload(db_session, d.id)
        assert row.status == "dead"

    async def test_batch_picks_due_only(self, _patch_db, db_session, sample_agent):
        from cloud.relay import forwarder
        due = await self._pending(db_session, sample_agent)
        not_due = await self._pending(
            db_session, sample_agent,
            next_attempt_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        delivered = []

        async def fake_deliver(delivery_id, client):
            delivered.append(delivery_id)

        with patch.object(forwarder, "deliver_one", fake_deliver):
            await forwarder.run_pending_batch(None)
        assert due.id in delivered and not_due.id not in delivered


# ── Provisioning env ─────────────────────────────────────────────────────────

class TestProvisionEnv:
    def test_relay_secret_in_env_derivation(self):
        agent_id = str(uuid.uuid4())
        secret = derive_relay_secret("root", agent_id)
        assert len(secret) == 64
        assert secret != derive_relay_secret("root", str(uuid.uuid4()))


# ── Gateway capture ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestGatewayCapture:
    async def test_capture_upserts_links(self, _patch_db, db_session, sample_agent):
        from cloud.relay.capture import capture_from_gateway_response
        body = json.dumps({
            "items": [{"id": "ca_captured_1", "appUniqueId": "gmail"}]
        }).encode()
        await capture_from_gateway_response(sample_agent.id, "application/json", body)
        link = (await db_session.execute(
            select(ComposioAccountLink).where(
                ComposioAccountLink.connected_account_id == "ca_captured_1"
            )
        )).scalar_one()
        assert link.agent_id == sample_agent.id and link.source == "gateway"

    async def test_capture_swallows_garbage(self, _patch_db, sample_agent):
        from cloud.relay.capture import capture_from_gateway_response
        await capture_from_gateway_response(sample_agent.id, "application/json", b"not json")
        await capture_from_gateway_response(sample_agent.id, "text/html", b"<html>")
