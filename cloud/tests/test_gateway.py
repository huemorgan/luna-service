"""Credential gateway tests — crypto, tokens, key resolution, proxy flows."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from cloud.db.models import GatewayKey, GatewayService, GatewayTenantToken, UsageEvent
from cloud.gateway.crypto import decrypt_key, encrypt_key
from cloud.gateway.keys import mark_key_failure, resolve_keys
from cloud.gateway.metering import UsageScanner
from cloud.gateway.provision_env import build_gateway_env
from cloud.gateway.registry import default_names, parse_auth_style, seed_services
from cloud.gateway.tokens import issue_token, verify_token

pytestmark = pytest.mark.asyncio


# ── Crypto ────────────────────────────────────────────────────────────────────

async def test_encrypt_decrypt_roundtrip():
    token = encrypt_key("sk-ant-secret-123")
    assert "sk-ant-secret-123" not in token
    assert decrypt_key(token) == "sk-ant-secret-123"


async def test_encrypt_is_nondeterministic():
    assert encrypt_key("same") != encrypt_key("same")


# ── Auth style parsing ───────────────────────────────────────────────────────

async def test_parse_auth_styles():
    a = parse_auth_style("header:x-api-key")
    assert a.header == "x-api-key" and a.scheme is None
    assert a.render("k") == "k"
    assert a.extract("k") == "k"

    b = parse_auth_style("header:Authorization:Bearer")
    assert b.header == "Authorization" and b.scheme == "Bearer"
    assert b.render("k") == "Bearer k"
    assert b.extract("Bearer k") == "k"
    assert b.extract("k") == "k"

    with pytest.raises(ValueError):
        parse_auth_style("query:apikey")


async def test_default_names():
    names = default_names("echo-test")
    assert names["luna_credential_name"] == "echo-test_api_key"
    assert names["luna_env_key_var"] == "LUNA_ECHO_TEST_API_KEY"
    assert names["luna_env_base_url_var"] == "LUNA_ECHO_TEST_BASE_URL"


# ── Registry seeding ─────────────────────────────────────────────────────────

async def test_seed_services_idempotent(db_session):
    await seed_services(db_session)
    await db_session.commit()
    slugs = {s.slug for s in (await db_session.execute(select(GatewayService))).scalars()}
    assert {"anthropic", "openai", "tavily", "composio"} <= slugs

    composio = (await db_session.execute(
        select(GatewayService).where(GatewayService.slug == "composio")
    )).scalar_one()
    assert composio.enabled is False
    assert composio.luna_credential_name == "plugin_connectors.composio.api_key"

    # Second run adds nothing and doesn't overwrite edits
    composio.enabled = True
    await db_session.commit()
    await seed_services(db_session)
    await db_session.commit()
    composio2 = (await db_session.execute(
        select(GatewayService).where(GatewayService.slug == "composio")
    )).scalar_one()
    assert composio2.enabled is True


# ── Tenant tokens ────────────────────────────────────────────────────────────

async def test_token_issue_verify_rotate(db_session, sample_agent):
    raw1 = await issue_token(db_session, sample_agent.id)
    await db_session.commit()
    assert raw1.startswith("lsv1-")
    assert await verify_token(db_session, raw1) == sample_agent.id

    # Reissue revokes the old token
    raw2 = await issue_token(db_session, sample_agent.id)
    await db_session.commit()
    assert await verify_token(db_session, raw1) is None
    assert await verify_token(db_session, raw2) == sample_agent.id

    assert await verify_token(db_session, "lsv1-garbage") is None
    assert await verify_token(db_session, "sk-not-a-token") is None

    # Raw value never stored
    rows = (await db_session.execute(select(GatewayTenantToken))).scalars().all()
    assert all(raw2 not in r.token_hash for r in rows)


# ── Key resolution ───────────────────────────────────────────────────────────

async def _add_service(db, slug="echo-test", **over):
    fields = {
        "slug": slug, "display_name": slug, "upstream_url": "http://upstream.test",
        "auth_style": "header:x-api-key", **default_names(slug), **over,
    }
    svc = GatewayService(**fields)
    db.add(svc)
    await db.flush()
    return svc


async def _add_key(db, slug, *, scope="global", priority=1, value="k", label="", active=True, cooldown=None):
    key = GatewayKey(
        service_slug=slug, scope=scope, priority=priority,
        api_key_enc=encrypt_key(value), label=label, is_active=active,
        cooldown_until=cooldown,
    )
    db.add(key)
    await db.flush()
    return key


async def test_resolution_order_and_cooldown(db_session, sample_agent):
    await _add_service(db_session)
    k_g1 = await _add_key(db_session, "echo-test", priority=1, value="G1")
    k_g2 = await _add_key(db_session, "echo-test", priority=2, value="G2")
    k_agent = await _add_key(
        db_session, "echo-test", scope=f"agent:{sample_agent.id}", priority=1, value="A1",
    )
    await db_session.commit()

    # Agent-scoped first, then global by priority
    keys = await resolve_keys(db_session, "echo-test", sample_agent.id)
    assert [k.id for k in keys] == [k_agent.id, k_g1.id, k_g2.id]

    # Other agents see only global
    keys = await resolve_keys(db_session, "echo-test", uuid.uuid4())
    assert [k.id for k in keys] == [k_g1.id, k_g2.id]

    # No agent → global only
    keys = await resolve_keys(db_session, "echo-test", None)
    assert [k.id for k in keys] == [k_g1.id, k_g2.id]

    # Cooldown skips
    await mark_key_failure(db_session, k_g1.id, 401)
    await db_session.commit()
    keys = await resolve_keys(db_session, "echo-test", None)
    assert [k.id for k in keys] == [k_g2.id]
    refreshed = (await db_session.execute(
        select(GatewayKey).where(GatewayKey.id == k_g1.id)
    )).scalar_one()
    assert refreshed.cooldown_until > datetime.now(timezone.utc) + timedelta(minutes=30)

    # Inactive skips
    k_g2.is_active = False
    await db_session.commit()
    assert await resolve_keys(db_session, "echo-test", None) == []


# ── Usage scanner ────────────────────────────────────────────────────────────

async def test_usage_scanner_anthropic_sse():
    s = UsageScanner("text/event-stream")
    s.feed(b'event: message_start\ndata: {"message":{"usage":{"input_tokens":120}}}\n\n')
    s.feed(b'event: message_delta\ndata: {"usage":{"output_tokens":45}}\n\n')
    assert s.input_tokens == 120 and s.output_tokens == 45


async def test_usage_scanner_openai_json_split_chunks():
    s = UsageScanner("application/json")
    payload = b'{"usage":{"prompt_tokens":300,"completion_tokens":77}}'
    s.feed(payload[:20])
    s.feed(payload[20:])
    assert s.input_tokens == 300 and s.output_tokens == 77


async def test_usage_scanner_ignores_non_json():
    s = UsageScanner("text/html")
    s.feed(b'"input_tokens": 999')
    assert s.input_tokens is None


# ── Proxy flows (full app, mocked upstream) ──────────────────────────────────

def _mock_upstream(rejected: set[str]):
    """MockTransport that echoes received auth headers, 401 for rejected keys."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = {
            k: v for k, v in request.headers.items()
            if k in ("x-api-key", "authorization")
        }
        bare = next(iter(auth.values()), "")
        if bare.lower().startswith("bearer "):
            bare = bare[7:]
        calls.append({"url": str(request.url), "auth": auth, "bare": bare})
        if bare in rejected:
            return httpx.Response(401, json={"error": "bad key"})
        return httpx.Response(200, json={"ok": True, "received": auth})

    return httpx.MockTransport(handler), calls


@pytest.fixture
def upstream(monkeypatch):
    transport, calls = _mock_upstream(rejected=set())
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr("cloud.api.gateway_proxy._get_client", lambda: client)
    return calls


@pytest.fixture
def upstream_rejecting(monkeypatch):
    rejected = {"REAL-G1"}
    transport, calls = _mock_upstream(rejected=rejected)
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr("cloud.api.gateway_proxy._get_client", lambda: client)
    return calls


async def test_proxy_managed_flow_injects_real_key(anon_client, db_session, sample_agent, upstream):
    await _add_service(db_session)
    key = await _add_key(db_session, "echo-test", value="REAL-G1", label="main")
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    r = await anon_client.get("/proxy/echo-test/v1/things", headers={"x-api-key": token})
    assert r.status_code == 200
    assert upstream[0]["bare"] == "REAL-G1"          # real key injected
    assert token not in json.dumps(upstream[0])       # token never forwarded

    events = (await db_session.execute(select(UsageEvent))).scalars().all()
    assert len(events) == 1
    ev = events[0]
    assert ev.billable is True
    assert ev.agent_id == sample_agent.id
    assert ev.key_id == key.id
    assert ev.service_slug == "echo-test"


async def test_proxy_invalid_token_401_never_reaches_upstream(anon_client, db_session, upstream):
    await _add_service(db_session)
    await _add_key(db_session, "echo-test", value="REAL-G1")
    await db_session.commit()

    r = await anon_client.get("/proxy/echo-test/x", headers={"x-api-key": "lsv1-garbage"})
    assert r.status_code == 401
    assert upstream == []


async def test_proxy_unknown_or_disabled_service_404(anon_client, db_session, sample_agent, upstream):
    r = await anon_client.get("/proxy/nope/x", headers={"x-api-key": "anything"})
    assert r.status_code == 404

    await _add_service(db_session, slug="off-svc", enabled=False)
    await db_session.commit()
    r = await anon_client.get("/proxy/off-svc/x", headers={"x-api-key": "anything"})
    assert r.status_code == 404


async def test_proxy_fallback_to_priority_2(anon_client, db_session, sample_agent, upstream_rejecting):
    await _add_service(db_session)
    k1 = await _add_key(db_session, "echo-test", priority=1, value="REAL-G1")
    await _add_key(db_session, "echo-test", priority=2, value="REAL-G2")
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    r = await anon_client.get("/proxy/echo-test/x", headers={"x-api-key": token})
    assert r.status_code == 200                       # caller never sees the 401
    assert [c["bare"] for c in upstream_rejecting] == ["REAL-G1", "REAL-G2"]

    # Priority-1 key is on cooldown now (refresh: the app wrote in its own session)
    await db_session.refresh(k1)
    assert k1.cooldown_until is not None

    # Next request skips straight to G2 — no extra upstream attempt on G1
    r = await anon_client.get("/proxy/echo-test/x", headers={"x-api-key": token})
    assert r.status_code == 200
    assert [c["bare"] for c in upstream_rejecting][-1] == "REAL-G2"
    assert len(upstream_rejecting) == 3


async def test_proxy_agent_override_beats_global(anon_client, db_session, sample_agent, account, admin_user, upstream):
    from cloud.db.models import Agent
    other = Agent(
        account_id=account.id, creator_id=admin_user.id, name="Other",
        slug="test-account-other", status="running",
    )
    db_session.add(other)
    await db_session.flush()

    await _add_service(db_session)
    await _add_key(db_session, "echo-test", value="REAL-G1")
    await _add_key(db_session, "echo-test", scope=f"agent:{sample_agent.id}", value="REAL-DEDICATED")
    tok_a = await issue_token(db_session, sample_agent.id)
    tok_b = await issue_token(db_session, other.id)
    await db_session.commit()

    r = await anon_client.get("/proxy/echo-test/x", headers={"x-api-key": tok_a})
    assert r.status_code == 200
    r = await anon_client.get("/proxy/echo-test/x", headers={"x-api-key": tok_b})
    assert r.status_code == 200
    assert [c["bare"] for c in upstream] == ["REAL-DEDICATED", "REAL-G1"]


async def test_proxy_byok_passthrough(anon_client, db_session, sample_agent, upstream):
    await _add_service(db_session)
    await _add_key(db_session, "echo-test", value="REAL-G1")
    await db_session.commit()

    r = await anon_client.get("/proxy/echo-test/x", headers={"x-api-key": "sk-tenant-own-key"})
    assert r.status_code == 200
    assert upstream[0]["bare"] == "sk-tenant-own-key"  # forwarded unchanged

    events = (await db_session.execute(select(UsageEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].billable is False
    assert events[0].agent_id is None
    assert events[0].key_id is None


async def test_proxy_byok_failure_no_fallback(anon_client, db_session, upstream_rejecting):
    await _add_service(db_session)
    await _add_key(db_session, "echo-test", value="REAL-G2")
    await db_session.commit()

    r = await anon_client.get("/proxy/echo-test/x", headers={"x-api-key": "REAL-G1"})
    assert r.status_code == 401                        # upstream error verbatim
    assert len(upstream_rejecting) == 1                # no retry with our keys


async def test_proxy_bearer_auth_style(anon_client, db_session, sample_agent, upstream):
    await _add_service(db_session, slug="bearer-svc", auth_style="header:Authorization:Bearer")
    await _add_key(db_session, "bearer-svc", value="REAL-B1")
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    r = await anon_client.get(
        "/proxy/bearer-svc/v1/chat", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert upstream[0]["auth"]["authorization"] == "Bearer REAL-B1"


# ── Provisioning env ─────────────────────────────────────────────────────────

async def test_build_gateway_env(db_session, sample_agent, monkeypatch):
    monkeypatch.setenv("LUNA_TAVILY_API_KEY", "tvly-real-key")
    monkeypatch.setenv("LUNA_ANTHROPIC_API_KEY", "sk-ant-real")  # must NOT leak
    await seed_services(db_session)
    await db_session.commit()

    env = await build_gateway_env(db_session, sample_agent.id)
    await db_session.commit()

    assert env["LUNA_ANTHROPIC_BASE_URL"].endswith("/proxy/anthropic")
    assert env["LUNA_OPENAI_BASE_URL"].endswith("/proxy/openai")
    assert env["LUNA_ANTHROPIC_API_KEY"].startswith("lsv1-")
    assert env["LUNA_OPENAI_API_KEY"] == env["LUNA_ANTHROPIC_API_KEY"]
    assert env["LUNA_HOST_NAME"]
    # SDK-standard mirrors for the pydantic-ai chat path (014)
    assert env["ANTHROPIC_BASE_URL"] == env["LUNA_ANTHROPIC_BASE_URL"]
    assert env["ANTHROPIC_API_KEY"] == env["LUNA_ANTHROPIC_API_KEY"]
    assert env["OPENAI_BASE_URL"] == env["LUNA_OPENAI_BASE_URL"]
    assert env["OPENAI_API_KEY"] == env["LUNA_OPENAI_API_KEY"]
    # Legacy exception until Luna 007.001
    assert env["LUNA_TAVILY_API_KEY"] == "tvly-real-key"
    # The real Anthropic key must not appear anywhere
    assert "sk-ant-real" not in json.dumps(env)
    # Composio disabled → not provisioned
    assert "LUNA_COMPOSIO_BASE_URL" not in env

    # The injected token is valid
    agent_id = await verify_token(db_session, env["LUNA_ANTHROPIC_API_KEY"])
    assert agent_id == sample_agent.id


# ── Admin API ────────────────────────────────────────────────────────────────

async def test_admin_services_crud_and_key_write_only(admin_client, db_session):
    await seed_services(db_session)
    await db_session.commit()

    r = await admin_client.get("/api/admin/gateway/services")
    assert r.status_code == 200
    assert {s["slug"] for s in r.json()} >= {"anthropic", "openai", "tavily", "composio"}

    # Dynamic add — no code, no restart
    r = await admin_client.post("/api/admin/gateway/services", json={
        "slug": "echo-test", "display_name": "Echo",
        "upstream_url": "http://localhost:9009", "auth_style": "header:x-api-key",
    })
    assert r.status_code == 201
    assert r.json()["luna_env_key_var"] == "LUNA_ECHO_TEST_API_KEY"

    # Add a key; response must not contain the value
    r = await admin_client.post("/api/admin/gateway/services/echo-test/keys", json={
        "api_key": "real-key-AAA", "label": "echo-main", "priority": 1,
    })
    assert r.status_code == 201
    assert "real-key-AAA" not in r.text

    # Listing keys never leaks values either
    r = await admin_client.get("/api/admin/gateway/services/echo-test/keys")
    assert r.status_code == 200
    assert "real-key-AAA" not in r.text
    assert r.json()[0]["label"] == "echo-main"

    # Duplicate (scope, priority) rejected
    r = await admin_client.post("/api/admin/gateway/services/echo-test/keys", json={
        "api_key": "real-key-BBB", "label": "dup", "priority": 1,
    })
    assert r.status_code == 409

    # Stored encrypted
    row = (await db_session.execute(select(GatewayKey))).scalars().first()
    assert "real-key-AAA" not in row.api_key_enc
    assert decrypt_key(row.api_key_enc) == "real-key-AAA"


async def test_admin_gateway_requires_admin(regular_client):
    r = await regular_client.get("/api/admin/gateway/services")
    assert r.status_code in (401, 403)
