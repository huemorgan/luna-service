"""039/004 — gateway metering & enforcement: route catalog, adapters, rating,
mode matrix, holds/settlement, block contract, header hygiene."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from cloud.billing import ledger, rating
from cloud.billing import worker as billing_worker
from cloud.billing.models import (
    AgentCreditLimit,
    AgentHostingPeriod,
    BillableEvent,
    BillingHold,
    RatedCharge,
)
from cloud.billing.rating import AttemptFacts
from cloud.billing.seed import seed_billing
from cloud.db.models import GatewayKey, GatewayModel, GatewayService
from cloud.gateway import adapters, enforcement, route_catalog
from cloud.gateway.crypto import encrypt_key
from cloud.gateway.registry import default_names
from cloud.gateway.tokens import issue_token

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_rating_caches():
    rating.invalidate_rating_caches()
    yield
    rating.invalidate_rating_caches()


@pytest.fixture(autouse=True)
def _inline_key_bookkeeping(monkeypatch):
    """The fire-and-forget mark_key_used task opens a DB session concurrently
    with finalize's session. On the test engine (one shared in-memory SQLite
    connection) those interleaved transactions clobber each other — a test
    artifact only; Postgres gives every session its own connection."""
    async def _noop(key_id):
        return None
    monkeypatch.setattr("cloud.api.gateway_proxy._mark_key_used_bg", _noop)


# ── Route catalog ─────────────────────────────────────────────────────────────

async def test_route_classification():
    billed = route_catalog.classify("anthropic", "POST", "v1/messages")
    assert billed.kind == "billed" and billed.adapter == "anthropic.messages"
    assert billed.sku == "llm_call"

    free = route_catalog.classify("anthropic", "POST", "v1/messages/count_tokens")
    assert free.kind == "free"
    assert route_catalog.classify("openai", "GET", "v1/models").kind == "free"
    assert route_catalog.classify("openai", "GET", "v1/models/gpt-4o").kind == "free"

    chat = route_catalog.classify("openai", "POST", "v1/chat/completions")
    assert chat.adapter == "openai.chat"
    emb = route_catalog.classify("openai", "POST", "v1/embeddings")
    assert emb.adapter == "openai.embeddings"

    # OpenAI-compatible SDKs against /proxy/{slug} send BARE paths (the /v1
    # lives in upstream_url) — the bare variants must classify identically.
    assert route_catalog.classify("openai", "POST", "chat/completions").adapter == "openai.chat"
    assert route_catalog.classify("openai", "POST", "embeddings").adapter == "openai.embeddings"
    assert route_catalog.classify("openai", "GET", "models").kind == "free"

    grok = route_catalog.classify("xai", "POST", "chat/completions")
    assert grok.kind == "billed" and grok.adapter == "xai.chat" and grok.sku == "llm_call"
    assert route_catalog.classify("xai", "GET", "models").kind == "free"
    assert route_catalog.classify("xai", "GET", "models/grok-4.5").kind == "free"

    kimi = route_catalog.classify("moonshot", "POST", "chat/completions")
    assert kimi.kind == "billed" and kimi.adapter == "moonshot.chat" and kimi.sku == "llm_call"
    assert route_catalog.classify("moonshot", "GET", "models").kind == "free"
    assert route_catalog.classify("moonshot", "GET", "models/kimi-k3").kind == "free"

    qwen = route_catalog.classify("qwen", "POST", "chat/completions")
    assert qwen.kind == "billed" and qwen.adapter == "qwen.chat" and qwen.sku == "llm_call"
    assert route_catalog.classify("qwen", "GET", "models").kind == "free"
    assert route_catalog.classify("qwen", "GET", "models/qwen3.8-max").kind == "free"

    # Browser Use rides a service-wide default (_SERVICE_DEFAULTS): the whole
    # v3 surface is free-interim, so no path on the service can 402 as
    # sku_unpriced (the vaselin-scanny-2 incident, 2026-08-25).
    assert route_catalog.classify("browser-use", "GET", "browsers").kind == "free"
    assert route_catalog.classify("browser-use", "POST", "browsers").kind == "free"
    assert route_catalog.classify("browser-use", "POST", "tasks").kind == "free"
    assert route_catalog.classify("browser-use", "GET", "tasks/task-123").kind == "free"
    # Deny-by-default is untouched for services without rows or a default.
    assert route_catalog.classify("giphy", "GET", "gifs/search") is None


async def test_every_enabled_seed_service_has_billing_coverage():
    """A registry service must never ship provisioned-but-blocked again: every
    enabled seed service needs a catalog row or a service default, or enforce
    mode 402s all its traffic as sku_unpriced before upstream."""
    from cloud.gateway.registry import SEED_SERVICES

    covered = route_catalog.covered_services()
    missing = {s["slug"] for s in SEED_SERVICES if s["enabled"]} - covered
    assert not missing, (
        f"enabled gateway services with no route_catalog coverage: {sorted(missing)} — "
        "add billed/free rows or a _SERVICE_DEFAULTS entry before enabling"
    )


async def test_xai_chat_adapter_openai_compatible():
    # xai.chat speaks the OpenAI protocol but excludes reasoning tokens from
    # completion_tokens while billing them as output (verified against a live
    # response's cost_in_usd_ticks) — the collector must add them back.
    c = adapters.make_collector("xai.chat", "application/json")
    c.feed(json.dumps({
        "id": "resp-1", "model": "grok-4.5",
        "usage": {"prompt_tokens": 120, "completion_tokens": 30,
                  "prompt_tokens_details": {"cached_tokens": 20},
                  "completion_tokens_details": {"reasoning_tokens": 129}},
    }).encode())
    facts = c.finish(200, {})
    assert facts.dimensions == {
        "input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 159,
    }
    assert facts.model == "grok-4.5"

    # OpenAI folds reasoning into completion_tokens — no double count there.
    c = adapters.make_collector("openai.chat", "application/json")
    c.feed(json.dumps({
        "id": "resp-2", "model": "gpt-4o",
        "usage": {"prompt_tokens": 10, "completion_tokens": 40,
                  "completion_tokens_details": {"reasoning_tokens": 30}},
    }).encode())
    assert c.finish(200, {}).dimensions["output_tokens"] == 40

    body = {"model": "grok-4.5", "stream": True, "messages": []}
    out = adapters.prepare_managed_body("xai.chat", body, json.dumps(body).encode())
    assert json.loads(out)["stream_options"] == {"include_usage": True}


async def test_gemini_chat_route_and_adapter():
    # 050: Gemini reasoning rides Google's OpenAI-compat surface. The agent
    # points its OpenAI client at /proxy/gemini/openai, so the bare path is
    # /openai/chat/completions — billed as an llm_call under the gemini provider.
    r = route_catalog.classify("gemini", "POST", "openai/chat/completions")
    assert r.kind == "billed" and r.adapter == "gemini.chat" and r.sku == "llm_call"
    assert adapters.provider_for_adapter("gemini.chat") == "gemini"
    assert route_catalog.classify("gemini", "GET", "openai/models").kind == "free"
    assert route_catalog.classify("gemini", "GET", "openai/models/gemini-3-pro").kind == "free"
    # The native image-gen route is untouched by the new OpenAI-compat rows.
    assert route_catalog.classify(
        "gemini", "POST", "models/gemini-3-pro-image:generateContent").adapter == "gemini.generate"

    # gemini.chat parses OpenAI-shaped usage like the plain OpenAI collector.
    c = adapters.make_collector("gemini.chat", "application/json")
    c.feed(json.dumps({
        "id": "resp-g", "model": "gemini-3-pro",
        "usage": {"prompt_tokens": 100, "completion_tokens": 40,
                  "prompt_tokens_details": {"cached_tokens": 10}},
    }).encode())
    facts = c.finish(200, {})
    assert facts.dimensions == {
        "input_tokens": 90, "cached_input_tokens": 10, "output_tokens": 40,
    }
    assert facts.model == "gemini-3-pro"

    # Managed streams get usage frames injected (OpenAI-compat contract).
    body = {"model": "gemini-3-pro", "stream": True, "messages": []}
    out = adapters.prepare_managed_body("gemini.chat", body, json.dumps(body).encode())
    assert json.loads(out)["stream_options"] == {"include_usage": True}


async def test_route_unknown_is_none():
    assert route_catalog.classify("anthropic", "POST", "v1/complete") is None
    assert route_catalog.classify("anthropic", "DELETE", "v1/messages") is None
    assert route_catalog.classify("tavily", "POST", "search").kind == "free"
    # Wildcard matches exactly one segment — deeper paths stay unknown.
    assert route_catalog.classify("openai", "GET", "v1/models/a/b") is None


async def test_route_path_normalization():
    assert route_catalog.normalize_path("v1//messages/") == "/v1/messages"
    assert route_catalog.classify("anthropic", "POST", "/v1//messages/").kind == "billed"


# ── Image generation (041) ───────────────────────────────────────────────────

async def test_image_route_classification():
    for model in ("gemini-3-pro-image", "gemini-2.5-flash-image"):
        r = route_catalog.classify("gemini", "POST", f"models/{model}:generateContent")
        assert r.kind == "billed" and r.adapter == "gemini.generate" and r.sku == "image_gen"
    assert route_catalog.classify("gemini", "GET", "models").kind == "free"
    assert route_catalog.classify("gemini", "GET", "models/gemini-3-pro-image").kind == "free"
    # Deny-by-default holds for everything the explicit rows don't name.
    assert route_catalog.classify(
        "gemini", "POST", "models/gemini-3-pro-image:streamGenerateContent") is None
    assert route_catalog.classify(
        "gemini", "POST", "models/gemini-3-pro-image:countTokens") is None
    assert route_catalog.classify("gemini", "POST", "models/gemini-2.5-pro:generateContent") is None

    for path in ("images/generations", "images/edits",
                 "v1/images/generations", "v1/images/edits"):
        r = route_catalog.classify("openai", "POST", path)
        assert r.kind == "billed" and r.adapter == "openai.images" and r.sku == "image_gen"
    assert route_catalog.classify("openai", "POST", "images/variations") is None


# ── Composio (043) ───────────────────────────────────────────────────────────

async def test_composio_route_classification():
    # Everything plugin-connectors calls through the proxy is free (043) —
    # Composio is flat-rate to Luna, no per-call provider spend to meter.
    free = [
        ("GET", "toolkits"),
        ("GET", "toolkits/gmail"),
        ("GET", "tools"),
        ("POST", "tools/execute/GMAIL_SEND_EMAIL"),
        ("POST", "auth_configs"),
        ("POST", "connected_accounts"),
        ("POST", "connected_accounts/link"),
        ("GET", "connected_accounts/ca_123"),
        ("DELETE", "connected_accounts/ca_123"),
        ("GET", "triggers_types"),
        ("POST", "trigger_instances/GMAIL_NEW_GMAIL_MESSAGE/upsert"),
        ("DELETE", "trigger_instances/manage/ti_123"),
    ]
    for method, path in free:
        r = route_catalog.classify("composio", method, path)
        assert r is not None and r.kind == "free", (method, path)
    # Deny-by-default for everything else, including wrong wildcard arity.
    assert route_catalog.classify("composio", "POST", "toolkits") is None
    assert route_catalog.classify("composio", "GET", "tools/execute/x") is None
    assert route_catalog.classify("composio", "POST", "trigger_instances/a/b/upsert") is None
    assert route_catalog.classify("composio", "DELETE", "trigger_instances/ti_123") is None
    assert route_catalog.classify("composio", "POST", "tools/execute/a/b") is None
    assert route_catalog.classify("composio", "POST", "connected_accounts/ca_123") is None


async def test_extract_model():
    # Default: JSON body (existing adapters keep their behavior).
    assert adapters.extract_model("openai.chat", {"model": "gpt-4o"}, "chat/completions") == "gpt-4o"
    assert adapters.extract_model("openai.chat", None, "chat/completions") is None
    # Gemini: the model rides in the path, not the body.
    assert adapters.extract_model(
        "gemini.generate", None, "models/gemini-3-pro-image:generateContent"
    ) == "gemini-3-pro-image"
    assert adapters.extract_model(
        "gemini.generate", None, "/models/gemini-2.5-flash-image:generateContent"
    ) == "gemini-2.5-flash-image"
    # openai.images JSON body.
    assert adapters.extract_model(
        "openai.images", {"model": "gpt-image-1"}, "images/generations"
    ) == "gpt-image-1"
    # openai.images multipart (images/edits): model is a form field.
    boundary = "----x"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="image"; filename="s.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + b"\x89PNG\r\n\x1a\nBINARY\r\n" + (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="model"\r\n\r\n'
        "gpt-image-1\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    assert adapters.extract_model(
        "openai.images", None, "images/edits",
        f"multipart/form-data; boundary={boundary}", body,
    ) == "gpt-image-1"
    assert adapters.extract_model(
        "openai.images", None, "images/edits",
        f"multipart/form-data; boundary={boundary}", b"no model here",
    ) is None


async def test_gemini_generate_adapter():
    c = adapters.make_collector("gemini.generate", "application/json")
    c.feed(json.dumps({
        "responseId": "resp-g1", "modelVersion": "gemini-3-pro-image",
        "usageMetadata": {
            "promptTokenCount": 24,
            "candidatesTokenCount": 1147,
            "thoughtsTokenCount": 80,
            "candidatesTokensDetails": [
                {"modality": "IMAGE", "tokenCount": 1120},
                {"modality": "TEXT", "tokenCount": 27},
            ],
        },
    }).encode())
    facts = c.finish(200, {})
    # 1120 image tokens at the image rate; 27 text + 80 thinking at text rate.
    assert facts.dimensions == {
        "input_tokens": 24, "output_image_tokens": 1120, "output_text_tokens": 107,
    }
    assert facts.model == "gemini-3-pro-image"
    assert facts.provider_response_id == "resp-g1"

    # No per-modality detail → all candidate tokens billed as image output
    # (image-model-only route; the expensive dimension is the safe default).
    c = adapters.make_collector("gemini.generate", "application/json")
    c.feed(json.dumps({
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 1290},
    }).encode())
    assert c.finish(200, {}).dimensions == {
        "input_tokens": 10, "output_image_tokens": 1290,
    }

    # Oversized inline-image body → head/tail scan finds usageMetadata.
    c = adapters.make_collector("gemini.generate", "application/json")
    head = (b'{"candidates":[{"content":{"parts":[{"inlineData":{"data":"'
            + b"A" * (3 * 1024 * 1024) + b'"}}]}}],')
    tail = (b'"usageMetadata":{"promptTokenCount":24,"candidatesTokenCount":1290,'
            b'"candidatesTokensDetails":[{"modality":"IMAGE","tokenCount":1290}]},'
            b'"modelVersion":"gemini-2.5-flash-image","responseId":"resp-g2"}')
    _feed_split(c, head + tail, size=64 * 1024)
    facts = c.finish(200, {})
    assert facts.dimensions == {"input_tokens": 24, "output_image_tokens": 1290}
    assert facts.model == "gemini-2.5-flash-image"


async def test_openai_images_adapter():
    c = adapters.make_collector("openai.images", "application/json")
    c.feed(json.dumps({
        "created": 1, "data": [{"b64_json": "AAAA"}],
        "usage": {
            "input_tokens": 60, "output_tokens": 4160, "total_tokens": 4220,
            "input_tokens_details": {"text_tokens": 50, "image_tokens": 10},
        },
    }).encode())
    assert c.finish(200, {}).dimensions == {
        "input_text_tokens": 50, "input_image_tokens": 10, "output_tokens": 4160,
    }

    # Missing detail split → all input billed as text; total preserved.
    c = adapters.make_collector("openai.images", "application/json")
    c.feed(json.dumps({"usage": {"input_tokens": 60, "output_tokens": 1056}}).encode())
    assert c.finish(200, {}).dimensions == {
        "input_text_tokens": 60, "output_tokens": 1056,
    }

    # Oversized b64 payload → the default `usage` scan still bills.
    c = adapters.make_collector("openai.images", "application/json")
    payload = (b'{"created":1,"data":[{"b64_json":"' + b"B" * (3 * 1024 * 1024)
               + b'"}],"usage":{"input_tokens":60,"output_tokens":4160,'
               b'"input_tokens_details":{"text_tokens":50,"image_tokens":10}}}')
    _feed_split(c, payload, size=64 * 1024)
    assert c.finish(200, {}).dimensions == {
        "input_text_tokens": 50, "input_image_tokens": 10, "output_tokens": 4160,
    }


async def test_image_estimates():
    est = adapters.estimate_dimensions("gemini.generate", {}, 400)
    assert est == {"input_tokens": 100, "output_image_tokens": 2000}
    # Huge reference-image bodies don't inflate the text-priced input estimate.
    est = adapters.estimate_dimensions("gemini.generate", {}, 4 * 1024 * 1024)
    assert est["input_tokens"] == 4000
    est = adapters.estimate_dimensions("openai.images", {"n": 2}, 200)
    assert est == {"input_text_tokens": 50, "output_tokens": 12480}
    est = adapters.estimate_dimensions("openai.images", None, 2_000_000)
    assert est == {"input_text_tokens": 4000, "output_tokens": 6240}


# ── Realtime voice (mint-billed sessions) ────────────────────────────────────

async def test_realtime_mint_route_classification():
    for path in ("realtime/client_secrets", "v1/realtime/client_secrets"):
        r = route_catalog.classify("openai", "POST", path)
        assert r.kind == "billed" and r.adapter == "openai.realtime_mint"
        assert r.sku == "voice_session"
    # The mint row must not open up the rest of the Realtime surface.
    assert route_catalog.classify("openai", "GET", "realtime/client_secrets") is None
    assert route_catalog.classify("openai", "POST", "realtime/sessions") is None


async def test_realtime_mint_adapter():
    # GA mint response: key in `value`, session metadata nested.
    c = adapters.make_collector("openai.realtime_mint", "application/json")
    c.feed(json.dumps({
        "value": "ek_abc", "expires_at": 1,
        "session": {"id": "sess_1", "model": "gpt-realtime-2.1", "type": "realtime"},
    }).encode())
    facts = c.finish(200, {})
    assert facts.dimensions == {"sessions": 1}
    assert facts.model == "gpt-realtime-2.1"
    assert facts.provider_response_id == "sess_1"
    assert facts.usage_seen

    # Older beta shape nests the key under client_secret.
    c = adapters.make_collector("openai.realtime_mint", "application/json")
    c.feed(json.dumps({"client_secret": {"value": "ek_x"}, "id": "sess_2"}).encode())
    assert c.finish(200, {}).dimensions == {"sessions": 1}

    # An error body mints nothing — no phantom session.
    c = adapters.make_collector("openai.realtime_mint", "application/json")
    c.feed(json.dumps({"error": {"message": "nope"}}).encode())
    facts = c.finish(401, {})
    assert facts.dimensions == {} and not facts.usage_seen

    # Model extraction covers both body shapes; estimate is one flat session.
    assert adapters.extract_model(
        "openai.realtime_mint", {"session": {"model": "gpt-realtime-2.1"}}, "") == "gpt-realtime-2.1"
    assert adapters.extract_model(
        "openai.realtime_mint", {"model": "gpt-realtime-2.1-mini"}, "") == "gpt-realtime-2.1-mini"
    assert adapters.estimate_dimensions("openai.realtime_mint", {}, 500) == {"sessions": 1}


# ── Adapters: Anthropic ──────────────────────────────────────────────────────

def _feed_split(collector, payload: bytes, size: int = 7):
    """Feed in tiny chunks so frames cross every chunk boundary."""
    for i in range(0, len(payload), size):
        collector.feed(payload[i:i + size])


async def test_anthropic_sse_with_cache_and_chunk_splits():
    c = adapters.make_collector("anthropic.messages", "text/event-stream")
    start = json.dumps({
        "type": "message_start",
        "message": {"id": "msg_01", "model": "claude-opus-4-6", "usage": {
            "input_tokens": 100, "output_tokens": 1,
            "cache_creation_input_tokens": 40, "cache_read_input_tokens": 300,
        }},
    })
    delta = json.dumps({"type": "message_delta", "usage": {"output_tokens": 55}})
    payload = f"event: message_start\ndata: {start}\n\nevent: message_delta\ndata: {delta}\n\n"
    _feed_split(c, payload.encode())
    facts = c.finish(200, {"request-id": "req_abc"})
    assert facts.dimensions == {
        "input_tokens": 100, "output_tokens": 55,
        "cache_creation_input_tokens": 40, "cache_read_input_tokens": 300,
    }
    assert facts.model == "claude-opus-4-6"
    assert facts.provider_request_id == "req_abc"
    assert facts.provider_response_id == "msg_01"
    assert facts.usage_seen


async def test_anthropic_duplicate_frames_never_double_count():
    c = adapters.make_collector("anthropic.messages", "text/event-stream")
    delta = f'data: {json.dumps({"type": "message_delta", "usage": {"output_tokens": 90}})}\n\n'
    start = json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 10}}})
    c.feed(f"data: {start}\n\n".encode())
    c.feed(delta.encode())
    c.feed(delta.encode())  # replayed cumulative frame
    facts = c.finish(200, {})
    assert facts.dimensions["output_tokens"] == 90  # max-merge, not sum


async def test_anthropic_json_body():
    c = adapters.make_collector("anthropic.messages", "application/json")
    body = json.dumps({
        "id": "msg_02", "model": "claude-haiku-4-5-20251001",
        "usage": {"input_tokens": 12, "output_tokens": 34},
        "content": [{"type": "text", "text": "SECRET-OUTPUT"}],
    }).encode()
    _feed_split(c, body)
    facts = c.finish(200, {})
    assert facts.dimensions == {"input_tokens": 12, "output_tokens": 34}
    # Only counters/ids/model survive — never content.
    assert "SECRET-OUTPUT" not in json.dumps(facts.dimensions)


async def test_anthropic_missing_usage():
    c = adapters.make_collector("anthropic.messages", "application/json")
    c.feed(json.dumps({"type": "error", "error": {"message": "overloaded"}}).encode())
    facts = c.finish(529, {})
    assert facts.dimensions == {} and not facts.usage_seen


async def test_anthropic_nested_cache_creation_object():
    # Newer API shape: usage.cache_creation = {ephemeral_5m_input_tokens: N, ...}
    c = adapters.make_collector("anthropic.messages", "application/json")
    c.feed(json.dumps({"usage": {
        "input_tokens": 5, "output_tokens": 6,
        "cache_creation": {"ephemeral_5m_input_tokens": 70, "ephemeral_1h_input_tokens": 30},
    }}).encode())
    facts = c.finish(200, {})
    assert facts.dimensions["cache_creation_input_tokens"] == 100


# ── Adapters: OpenAI ─────────────────────────────────────────────────────────

async def test_openai_chat_cached_tokens_not_double_billed():
    c = adapters.make_collector("openai.chat", "application/json")
    c.feed(json.dumps({
        "id": "chatcmpl-1", "model": "gpt-4o",
        "usage": {"prompt_tokens": 1000, "completion_tokens": 50,
                  "prompt_tokens_details": {"cached_tokens": 800}},
    }).encode())
    facts = c.finish(200, {"x-request-id": "req_oai"})
    assert facts.dimensions == {
        "input_tokens": 200, "cached_input_tokens": 800, "output_tokens": 50,
    }
    assert facts.provider_request_id == "req_oai"


async def test_openai_chat_sse_usage_final_frame():
    c = adapters.make_collector("openai.chat", "text/event-stream")
    chunk = json.dumps({"id": "chatcmpl-2", "model": "gpt-4o-mini",
                        "choices": [{"delta": {"content": "hi"}}], "usage": None})
    final = json.dumps({"id": "chatcmpl-2", "model": "gpt-4o-mini", "choices": [],
                        "usage": {"prompt_tokens": 20, "completion_tokens": 9}})
    payload = f"data: {chunk}\n\ndata: {final}\n\ndata: [DONE]\n\n"
    _feed_split(c, payload.encode(), size=5)
    facts = c.finish(200, {})
    assert facts.dimensions == {"input_tokens": 20, "output_tokens": 9}
    assert facts.model == "gpt-4o-mini"


async def test_openai_embeddings_oversized_body_scan():
    c = adapters.make_collector("openai.embeddings", "application/json")
    # >2MB body: usage lives in the tail; the full-JSON parse is abandoned.
    filler = '"' + "x" * (3 * 1024 * 1024) + '"'
    body = ('{"object":"list","data":[' + filler +
            '],"model":"text-embedding-3-small","usage":{"prompt_tokens":777,"total_tokens":777}}')
    _feed_split(c, body.encode(), size=64 * 1024)
    facts = c.finish(200, {})
    assert facts.dimensions == {"input_tokens": 777}


async def test_prepare_managed_body_injects_include_usage():
    body_json = {"model": "gpt-4o", "stream": True, "messages": []}
    out = adapters.prepare_managed_body("openai.chat", body_json, json.dumps(body_json).encode())
    assert json.loads(out)["stream_options"] == {"include_usage": True}

    # Non-stream and non-chat bodies pass through untouched.
    plain = json.dumps({"model": "gpt-4o", "messages": []}).encode()
    assert adapters.prepare_managed_body("openai.chat", json.loads(plain), plain) == plain
    assert adapters.prepare_managed_body("anthropic.messages", body_json, b"raw") == b"raw"

    # Existing stream_options keys survive the injection.
    withopts = {"model": "gpt-4o", "stream": True, "stream_options": {"other": 1}}
    out2 = adapters.prepare_managed_body("openai.chat", withopts, json.dumps(withopts).encode())
    assert json.loads(out2)["stream_options"] == {"other": 1, "include_usage": True}


async def test_estimate_dimensions():
    est = adapters.estimate_dimensions("anthropic.messages", {"max_tokens": 100}, 400)
    assert est == {"input_tokens": 100, "output_tokens": 100}
    est = adapters.estimate_dimensions("openai.chat", {}, 40)
    assert est == {"input_tokens": 10, "output_tokens": 8192}  # ceiling default
    assert adapters.estimate_dimensions("openai.embeddings", {}, 400) == {"input_tokens": 100}


# ── Rating math ──────────────────────────────────────────────────────────────

def _rates():
    return {
        ("anthropic", "claude-opus-4-6", "input_tokens"): (5, 1),
        ("anthropic", "claude-opus-4-6", "output_tokens"): (25, 1),
        ("anthropic", "claude-opus-4-6", "cache_read_input_tokens"): (1, 2),
    }


async def test_rate_call_single_ceil_and_margin():
    result = rating.rate_call(
        _rates(), margin_micro=20_000,
        attempts=[AttemptFacts(provider="anthropic", model="claude-opus-4-6",
                               dimensions={"input_tokens": 1000, "output_tokens": 500,
                                           "cache_read_input_tokens": 100},
                               billable=True)],
    )
    # 1000*5 + 500*25 + 100*(1/2) = 17,550 vendor + 20,000 margin = 37,550 → 4 credits
    assert result.vendor_micro_usd == 17_550
    assert result.credits == 4
    assert result.rounding_micro_usd == 40_000 - 37_550
    assert result.luna_absorbed_micro_usd == 0
    assert result.unrated_dimensions == []


async def test_rate_call_failed_attempt_absorbed_one_margin():
    result = rating.rate_call(
        _rates(), margin_micro=20_000,
        attempts=[
            AttemptFacts(provider="anthropic", model="claude-opus-4-6",
                         dimensions={"input_tokens": 1000}, billable=False, attempt_number=1),
            AttemptFacts(provider="anthropic", model="claude-opus-4-6",
                         dimensions={"input_tokens": 1000, "output_tokens": 100},
                         billable=True, attempt_number=2),
        ],
    )
    # Billable: 5,000 + 2,500 = 7,500 + one margin → 3 credits. Failed attempt absorbed.
    assert result.vendor_micro_usd == 7_500
    assert result.credits == 3
    assert result.luna_absorbed_micro_usd == 5_000


async def test_rate_call_unrated_dimension_recorded_never_guessed():
    result = rating.rate_call(
        _rates(), margin_micro=0,
        attempts=[AttemptFacts(provider="anthropic", model="claude-opus-4-6",
                               dimensions={"input_tokens": 10, "mystery_tokens": 5},
                               billable=True)],
    )
    assert result.unrated_dimensions == ["anthropic:claude-opus-4-6:mystery_tokens"]
    assert result.vendor_micro_usd == 50


async def test_model_tier_explicit_lists_only():
    config = {"top_tier_models": ["a"], "mid_tier_models": ["b"]}
    assert rating.model_tier(config, "a") == "top"
    assert rating.model_tier(config, "b") == "mid"
    assert rating.model_tier(config, "c") is None
    assert rating.model_tier(config, None) is None


# ── Integration fixtures ─────────────────────────────────────────────────────

def _anthropic_upstream(*, usage=True, rejected=frozenset()):
    """MockTransport imitating the Anthropic messages endpoint."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({
            "url": str(request.url),
            "headers": dict(request.headers),
            "body": request.content.decode() if request.content else "",
        })
        key = request.headers.get("x-api-key", "")
        if key in rejected:
            return httpx.Response(401, json={"error": "bad key"})
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, json={"data": []})
        payload = {"id": "msg_x", "model": "claude-opus-4-6",
                   "content": [{"type": "text", "text": "TOPSECRET-COMPLETION"}]}
        if usage:
            payload["usage"] = {"input_tokens": 1000, "output_tokens": 500}
        return httpx.Response(200, json=payload, headers={"request-id": "req_up1"})

    return httpx.MockTransport(handler), calls


@pytest.fixture
def anthropic_upstream(monkeypatch):
    transport, calls = _anthropic_upstream()
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr("cloud.api.gateway_proxy._get_client", lambda: client)
    return calls


async def _seed_billing_gateway(db, sample_agent, *, credits=100):
    """Anthropic service + key + token + catalog model + published pricing
    versions + funded wallet. Returns the tenant token."""
    db.add(GatewayService(
        slug="anthropic", display_name="Anthropic",
        upstream_url="http://upstream.test", auth_style="header:x-api-key",
        **default_names("anthropic"),
    ))
    db.add(GatewayKey(
        service_slug="anthropic", scope="global", priority=1,
        api_key_enc=encrypt_key("REAL-ANT-1"), label="main", is_active=True,
    ))
    db.add(GatewayModel(provider="anthropic", model="claude-opus-4-6",
                        kinds=["reasoning"], aliases=["opus"], enabled=True))
    await db.flush()
    await seed_billing(db)
    await ledger.ensure_billing_account(db, sample_agent.account_id)
    if credits:
        await ledger.create_grant(
            db, account_id=sample_agent.account_id, source_type="gift",
            source_key=f"test:{uuid.uuid4()}", credits=credits,
            visible_category="gift", effective_at=NOW - timedelta(days=1),
            expires_at=None, now=NOW,
        )
    token = await issue_token(db, sample_agent.id)
    await db.commit()
    return token


def _set_mode(monkeypatch, mode: str):
    monkeypatch.setattr("cloud.gateway.enforcement.billing_mode", lambda: mode)


_MSG_BODY = json.dumps({
    "model": "claude-opus-4-6", "max_tokens": 100,
    "messages": [{"role": "user", "content": "TOPSECRET-PROMPT"}],
})


async def _call_messages(client, token, *, body=_MSG_BODY, headers=None):
    return await client.post(
        "/proxy/anthropic/v1/messages",
        content=body,
        headers={"x-api-key": token, "content-type": "application/json", **(headers or {})},
    )


async def _rows(db, model):
    return (await db.execute(select(model))).scalars().all()


# ── Mode matrix ──────────────────────────────────────────────────────────────

async def test_mode_off_no_billing_rows(anon_client, db_session, sample_agent, anthropic_upstream):
    token = await _seed_billing_gateway(db_session, sample_agent, credits=0)
    r = await _call_messages(anon_client, token)  # default mode is off
    assert r.status_code == 200
    assert await _rows(db_session, BillableEvent) == []
    assert await _rows(db_session, RatedCharge) == []
    assert await _rows(db_session, BillingHold) == []


async def test_mode_observe_records_no_wallet_effect(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "observe")
    token = await _seed_billing_gateway(db_session, sample_agent, credits=0)  # empty wallet
    r = await _call_messages(anon_client, token)
    assert r.status_code == 200  # observe never blocks

    events = await _rows(db_session, BillableEvent)
    charges = await _rows(db_session, RatedCharge)
    assert len(events) == 1 and len(charges) == 1
    assert events[0].quantity_json == {"input_tokens": 1000, "output_tokens": 500}
    assert events[0].provider_request_id == "req_up1"
    assert charges[0].charge_status == "observed"
    # vendor 1000*5 + 500*25 = 17,500 + agent/top margin 20,000 → 4 credits
    assert charges[0].vendor_cost_micro_usd == 17_500
    assert charges[0].margin_micro_usd == 20_000
    assert charges[0].credits == 4
    assert await _rows(db_session, BillingHold) == []
    assert await ledger.posted_balance(db_session, sample_agent.account_id) == 0


async def test_mode_shadow_records_would_block_no_customer_effect(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "shadow")
    monkeypatch.setattr("cloud.billing.ledger.OVERDRAFT_LIMIT_CREDITS", 0)  # floor at 0
    token = await _seed_billing_gateway(db_session, sample_agent, credits=0)
    r = await _call_messages(anon_client, token)
    assert r.status_code == 200  # shadow never blocks

    charges = await _rows(db_session, RatedCharge)
    assert len(charges) == 1 and charges[0].charge_status == "shadow"
    assert charges[0].rule_snapshot["would_block"] == "credits_exhausted"
    assert await _rows(db_session, BillingHold) == []  # savepoint rolled back
    assert await ledger.posted_balance(db_session, sample_agent.account_id) == 0


async def test_mode_enforce_blocks_empty_wallet(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    monkeypatch.setattr("cloud.billing.ledger.OVERDRAFT_LIMIT_CREDITS", 0)  # floor at 0
    token = await _seed_billing_gateway(db_session, sample_agent, credits=0)
    r = await _call_messages(anon_client, token)
    assert r.status_code == 402
    err = r.json()["error"]
    assert err["code"] == "credits_exhausted" and err["type"] == "billing"
    assert err["retryable"] is False
    assert anthropic_upstream == []  # blocked before any provider contact


async def test_mode_enforce_happy_path_holds_and_settles(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    token = await _seed_billing_gateway(db_session, sample_agent, credits=100)
    r = await _call_messages(anon_client, token)
    assert r.status_code == 200

    holds = await _rows(db_session, BillingHold)
    assert len(holds) == 1 and holds[0].status == "open"

    # Durable settlement runs through the outbox worker.
    ran = await billing_worker.run_once(db_session, worker_id="test")
    await db_session.commit()
    assert ran == 1
    await db_session.refresh(holds[0])
    assert holds[0].status == "settled"
    charges = await _rows(db_session, RatedCharge)
    assert charges[0].charge_status == "settled"
    assert charges[0].credits == 4
    assert await ledger.posted_balance(db_session, sample_agent.account_id) == 96


async def test_mode_enforce_realtime_mint_flat_session_charge(
    anon_client, db_session, sample_agent, monkeypatch,
):
    """Voice mint is billed as one flat session: hold → upstream mint →
    settle at vendor session estimate + margin (520,000 µ$ → 52 credits)."""
    _set_mode(monkeypatch, "enforce")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/realtime/client_secrets")
        assert request.headers.get("authorization") == "Bearer REAL-OAI-1"
        return httpx.Response(200, json={
            "value": "ek_live", "expires_at": 9,
            "session": {"id": "sess_e2e", "model": "gpt-realtime-2.1", "type": "realtime"},
        }, headers={"x-request-id": "req_rt1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("cloud.api.gateway_proxy._get_client", lambda: client)

    db_session.add(GatewayService(
        slug="openai", display_name="OpenAI",
        upstream_url="http://upstream.test/v1", auth_style="header:Authorization:Bearer",
        **default_names("openai"),
    ))
    db_session.add(GatewayKey(
        service_slug="openai", scope="global", priority=1,
        api_key_enc=encrypt_key("REAL-OAI-1"), label="main", is_active=True,
    ))
    await db_session.flush()
    await seed_billing(db_session)
    await ledger.ensure_billing_account(db_session, sample_agent.account_id)
    await ledger.create_grant(
        db_session, account_id=sample_agent.account_id, source_type="gift",
        source_key=f"test:{uuid.uuid4()}", credits=100,
        visible_category="gift", effective_at=NOW - timedelta(days=1),
        expires_at=None, now=NOW,
    )
    token = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    r = await anon_client.post(
        "/proxy/openai/realtime/client_secrets",
        content=json.dumps({"session": {"type": "realtime", "model": "gpt-realtime-2.1"}}),
        headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["value"] == "ek_live"

    ran = await billing_worker.run_once(db_session, worker_id="test")
    await db_session.commit()
    assert ran == 1
    events = await _rows(db_session, BillableEvent)
    assert len(events) == 1
    assert events[0].sku == "voice_session"
    assert events[0].quantity_json == {"sessions": 1}
    assert events[0].model == "gpt-realtime-2.1"
    charges = await _rows(db_session, RatedCharge)
    assert charges[0].charge_status == "settled"
    assert charges[0].vendor_cost_micro_usd == 500_000
    assert charges[0].margin_micro_usd == 20_000
    assert charges[0].credits == 52
    assert await ledger.posted_balance(db_session, sample_agent.account_id) == 48


# ── Deny-by-default classification ───────────────────────────────────────────

async def test_enforce_unknown_route_blocked_before_upstream(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    token = await _seed_billing_gateway(db_session, sample_agent)
    r = await anon_client.post(
        "/proxy/anthropic/v1/complete", content=b"{}",
        headers={"x-api-key": token, "content-type": "application/json"},
    )
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "sku_unpriced"
    assert anthropic_upstream == []


async def test_observe_unknown_route_passes_with_would_block(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "observe")
    token = await _seed_billing_gateway(db_session, sample_agent)
    r = await anon_client.post(
        "/proxy/anthropic/v1/complete", content=b"{}",
        headers={"x-api-key": token, "content-type": "application/json"},
    )
    assert r.status_code == 200  # fails closed only in enforce
    events = await _rows(db_session, BillableEvent)
    assert len(events) == 1 and events[0].status == "would_block"
    assert events[0].quantity_json == {"would_block": "sku_unpriced"}


async def test_free_route_never_billed_even_broke(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    token = await _seed_billing_gateway(db_session, sample_agent, credits=0)
    r = await anon_client.get("/proxy/anthropic/v1/models", headers={"x-api-key": token})
    assert r.status_code == 200
    assert await _rows(db_session, BillableEvent) == []
    assert await _rows(db_session, BillingHold) == []


async def test_uncovered_model_fails_closed_enforce_only(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    token = await _seed_billing_gateway(db_session, sample_agent)
    # Enabled in the catalog AFTER publish — uncovered by the active version.
    db_session.add(GatewayModel(provider="anthropic", model="claude-new-1",
                                kinds=["reasoning"], aliases=[], enabled=True))
    await db_session.commit()
    body = json.dumps({"model": "claude-new-1", "max_tokens": 5, "messages": []})
    r = await _call_messages(anon_client, token, body=body)
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "sku_unpriced"
    assert anthropic_upstream == []


# ── Header hygiene & attribution ─────────────────────────────────────────────

async def test_x_luna_headers_stripped_and_attribution_unspoofable(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "observe")
    token = await _seed_billing_gateway(db_session, sample_agent)
    r = await _call_messages(anon_client, token, headers={
        "x-luna-call-id": "call-77",
        "x-luna-root-action-id": "act-9",
        "x-luna-root-action-type": "scheduled_run",
        "x-luna-channel": "scheduler",
        "x-luna-job-id": "trigger-abc",
        "x-luna-account-id": str(uuid.uuid4()),  # spoof attempt — ignored
    })
    assert r.status_code == 200
    upstream_headers = anthropic_upstream[0]["headers"]
    assert not any(h.startswith("x-luna-") for h in upstream_headers)

    ev = (await _rows(db_session, BillableEvent))[0]
    # Attribution comes from the authenticated token, never headers.
    assert ev.account_id == sample_agent.account_id
    assert ev.agent_id == sample_agent.id
    # Tenant call id is namespaced by agent — it can never dedupe across tenants.
    assert ev.call_id == f"{sample_agent.id}:call-77"
    assert ev.root_action_id == "act-9" and ev.root_action_type == "scheduled_run"
    # Origin dimensions (048): channel + stable job id ingested for usage.
    assert ev.channel == "scheduler"
    assert ev.job_id == "trigger-abc"


async def test_goalseek_run_root_action_type_accepted(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    """042/phase08: goal-seek wakes stamp root_action_type=goalseek_run — the
    allowlist must accept it (unknown types coerce to NULL and the spend folds
    into web, hiding what autonomous goal pursuit costs)."""
    _set_mode(monkeypatch, "observe")
    token = await _seed_billing_gateway(db_session, sample_agent)
    r = await _call_messages(anon_client, token, headers={
        "x-luna-root-action-type": "goalseek_run",
        "x-luna-job-id": "goalseek-goal-1",
    })
    assert r.status_code == 200
    ev = (await _rows(db_session, BillableEvent))[0]
    assert ev.root_action_type == "goalseek_run"
    assert ev.job_id == "goalseek-goal-1"


async def test_same_call_id_never_dedupes_a_charge(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "observe")
    token = await _seed_billing_gateway(db_session, sample_agent)
    for _ in range(2):
        r = await _call_messages(anon_client, token, headers={"x-luna-call-id": "same-id"})
        assert r.status_code == 200
    charges = await _rows(db_session, RatedCharge)
    events = await _rows(db_session, BillableEvent)
    assert len(charges) == 2 and len(events) == 2  # correlation only, never dedup
    assert len({c.logical_call_id for c in charges}) == 2


async def test_direct_context_is_bounded_margin_discount_only(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "observe")
    token = await _seed_billing_gateway(db_session, sample_agent)
    r = await _call_messages(anon_client, token, headers={"x-luna-context": "direct"})
    assert r.status_code == 200
    charge = (await _rows(db_session, RatedCharge))[0]
    # direct/top margin (10,000) instead of agent/top (20,000): the only
    # tenant-influenced input, bounded by the constant spread. Vendor unchanged.
    assert charge.margin_micro_usd == 10_000
    assert charge.vendor_cost_micro_usd == 17_500
    assert charge.rule_snapshot["context"] == "direct"


async def test_no_prompt_or_output_in_billing_rows(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "observe")
    token = await _seed_billing_gateway(db_session, sample_agent)
    await _call_messages(anon_client, token)
    for ev in await _rows(db_session, BillableEvent):
        blob = json.dumps({"q": ev.quantity_json, "m": ev.model, "ids": [
            ev.provider_request_id, ev.provider_response_id, ev.call_id]})
        assert "TOPSECRET" not in blob and "REAL-ANT-1" not in blob
    for ch in await _rows(db_session, RatedCharge):
        blob = json.dumps(ch.rule_snapshot)
        assert "TOPSECRET" not in blob and "REAL-ANT-1" not in blob


# ── Alias canonicalization ───────────────────────────────────────────────────

async def test_alias_resolves_to_canonical_model_and_tier(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "observe")
    token = await _seed_billing_gateway(db_session, sample_agent)
    body = json.dumps({"model": "opus", "max_tokens": 100, "messages": []})
    r = await _call_messages(anon_client, token, body=body)
    assert r.status_code == 200
    charge = (await _rows(db_session, RatedCharge))[0]
    assert charge.rule_snapshot["requested_model"] == "opus"
    assert charge.rule_snapshot["canonical_model"] == "claude-opus-4-6"
    assert charge.rule_snapshot["tier"] == "top"
    assert charge.credits == 4  # rated at the canonical model's tariff


# ── Blocked identities ───────────────────────────────────────────────────────

async def test_payment_due_blocks_in_enforce(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    token = await _seed_billing_gateway(db_session, sample_agent)
    db_session.add(AgentHostingPeriod(
        agent_id=sample_agent.id, account_id=sample_agent.account_id,
        starts_at=NOW - timedelta(days=30), ends_at=NOW, price_credits=999,
        state="payment_due",
    ))
    await db_session.commit()
    r = await _call_messages(anon_client, token)
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "hosting_payment_due"
    assert anthropic_upstream == []


async def test_luna_daily_limit_blocks_in_enforce(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    token = await _seed_billing_gateway(db_session, sample_agent, credits=1_000)
    db_session.add(AgentCreditLimit(agent_id=sample_agent.id, daily_limit_credits=1))
    await db_session.commit()
    r = await _call_messages(anon_client, token)
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "luna_daily_limit"
    assert anthropic_upstream == []


async def test_revoked_token_cannot_spend(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    await _seed_billing_gateway(db_session, sample_agent)
    revoked = await issue_token(db_session, sample_agent.id)  # old token…
    await issue_token(db_session, sample_agent.id)            # …revoked by reissue
    await db_session.commit()
    r = await _call_messages(anon_client, revoked)
    assert r.status_code == 401
    assert anthropic_upstream == []
    assert await _rows(db_session, BillingHold) == []


async def test_overdraft_admits_second_concurrent_uncovered_call(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    # 061: with a tiny balance and a hold already open, a second concurrent
    # call is no longer blocked on exposure — overdraft admits it. Both succeed;
    # the wallet settles into a small (bounded) debt.
    token = await _seed_billing_gateway(db_session, sample_agent, credits=1)
    r1 = await _call_messages(anon_client, token)
    assert r1.status_code == 200
    r2 = await _call_messages(anon_client, token)
    assert r2.status_code == 200
    assert len(await _rows(db_session, BillingHold)) == 2


# ── Failure states: exactly one explainable outcome ──────────────────────────

async def test_billing_store_failure_fails_closed_only_in_enforce(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    async def _boom(*a, **k):
        raise RuntimeError("billing db down")

    token = await _seed_billing_gateway(db_session, sample_agent)
    monkeypatch.setattr("cloud.billing.rating.resolve_commercial_version", _boom)

    _set_mode(monkeypatch, "observe")
    r = await _call_messages(anon_client, token)
    assert r.status_code == 200  # observe degrades open

    _set_mode(monkeypatch, "enforce")
    r = await _call_messages(anon_client, token)
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "billing_temporarily_unavailable"


async def test_usage_missing_goes_needs_reconciliation(
    anon_client, db_session, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    transport, _ = _anthropic_upstream(usage=False)
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr("cloud.api.gateway_proxy._get_client", lambda: client)

    token = await _seed_billing_gateway(db_session, sample_agent)
    r = await _call_messages(anon_client, token)
    assert r.status_code == 200

    # No settle/release was enqueued — provider spend is never silently dropped.
    assert await billing_worker.run_once(db_session, worker_id="test") == 0
    charge = (await _rows(db_session, RatedCharge))[0]
    assert charge.charge_status == "needs_reconciliation"
    ev = (await _rows(db_session, BillableEvent))[0]
    assert ev.cost_source == "estimated"
    est_input = -(-len(_MSG_BODY) // 4)
    assert ev.quantity_json == {"input_tokens": est_input, "output_tokens": 100}

    # The stale-hold reaper is the backstop: expired open hold → reconciliation.
    hold = (await _rows(db_session, BillingHold))[0]
    assert hold.status == "open"
    hold.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()
    assert await enforcement.reap_stale_holds_once(db_session) == 1
    await db_session.refresh(hold)
    assert hold.status == "needs_reconciliation"


async def test_upstream_unreachable_releases_hold(
    anon_client, db_session, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")

    def _handler(request):
        raise httpx.ConnectError("nope")

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr("cloud.api.gateway_proxy._get_client", lambda: client)

    token = await _seed_billing_gateway(db_session, sample_agent)
    r = await _call_messages(anon_client, token)
    assert r.status_code == 502

    assert await billing_worker.run_once(db_session, worker_id="test") == 1
    await db_session.commit()
    hold = (await _rows(db_session, BillingHold))[0]
    await db_session.refresh(hold)
    assert hold.status == "released"
    charge = (await _rows(db_session, RatedCharge))[0]
    assert charge.charge_status == "released"
    assert await ledger.posted_balance(db_session, sample_agent.account_id) == 100


async def test_fallback_attempt_absorbed_single_margin(
    anon_client, db_session, sample_agent, monkeypatch,
):
    _set_mode(monkeypatch, "enforce")
    transport, calls = _anthropic_upstream(rejected=frozenset({"REAL-ANT-1"}))
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr("cloud.api.gateway_proxy._get_client", lambda: client)

    token = await _seed_billing_gateway(db_session, sample_agent)
    db_session.add(GatewayKey(
        service_slug="anthropic", scope="global", priority=2,
        api_key_enc=encrypt_key("REAL-ANT-2"), label="backup", is_active=True,
    ))
    await db_session.commit()

    r = await _call_messages(anon_client, token)
    assert r.status_code == 200
    assert len(calls) == 2  # 401 on key 1, success on key 2

    events = await _rows(db_session, BillableEvent)
    assert len(events) == 2
    by_attempt = {e.attempt_number: e for e in events}
    assert by_attempt[1].quantity_json == {}          # failed attempt: no usage
    assert by_attempt[2].quantity_json["output_tokens"] == 500

    charges = await _rows(db_session, RatedCharge)
    assert len(charges) == 1
    assert charges[0].margin_micro_usd == 20_000      # exactly one margin
    assert charges[0].credits == 4

    assert await billing_worker.run_once(db_session, worker_id="test") == 1
    await db_session.commit()
    assert await ledger.posted_balance(db_session, sample_agent.account_id) == 96


async def test_byok_never_billed(anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch):
    _set_mode(monkeypatch, "enforce")
    await _seed_billing_gateway(db_session, sample_agent, credits=0)
    # A real provider key (not lsv1-) is BYOK passthrough — never classified,
    # never blocked, never billed, even with an empty wallet in enforce.
    r = await _call_messages(anon_client, "sk-ant-users-own-key")
    assert r.status_code == 200
    assert anthropic_upstream[0]["headers"]["x-api-key"] == "sk-ant-users-own-key"
    assert await _rows(db_session, BillableEvent) == []
    assert await _rows(db_session, BillingHold) == []


# ── Per-account enforcement overrides (039/010) ──────────────────────────────

async def test_override_enforce_blocks_while_global_off(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    from cloud.billing import modes

    _set_mode(monkeypatch, "off")
    monkeypatch.setattr("cloud.billing.ledger.OVERDRAFT_LIMIT_CREDITS", 0)  # floor at 0
    token = await _seed_billing_gateway(db_session, sample_agent, credits=0)
    await modes.set_override(db_session, sample_agent.account_id, "enforce")
    await db_session.commit()

    r = await _call_messages(anon_client, token)
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "credits_exhausted"
    assert anthropic_upstream == []


async def test_override_never_lowers_global_enforce(
    anon_client, db_session, sample_agent, anthropic_upstream, monkeypatch,
):
    from cloud.billing import modes

    _set_mode(monkeypatch, "enforce")
    monkeypatch.setattr("cloud.billing.ledger.OVERDRAFT_LIMIT_CREDITS", 0)  # floor at 0
    token = await _seed_billing_gateway(db_session, sample_agent, credits=0)
    await modes.set_override(db_session, sample_agent.account_id, "observe")
    await db_session.commit()

    r = await _call_messages(anon_client, token)
    assert r.status_code == 402  # effective mode = max(enforce, observe)
    assert anthropic_upstream == []


async def test_override_on_other_account_leaves_this_one_off(
    anon_client, db_session, admin_user, sample_agent, anthropic_upstream, monkeypatch,
):
    from cloud.billing import modes
    from cloud.db.models import Account

    _set_mode(monkeypatch, "off")
    token = await _seed_billing_gateway(db_session, sample_agent, credits=0)

    other = Account(slug="other-account", name="Other", created_by=admin_user.id)
    db_session.add(other)
    await db_session.flush()
    await modes.set_override(db_session, other.id, "enforce")
    await db_session.commit()

    # An override existing anywhere disables the zero-query fast path, but this
    # account's effective mode is still off: passthrough, zero billing rows.
    r = await _call_messages(anon_client, token)
    assert r.status_code == 200
    assert await _rows(db_session, BillableEvent) == []
    assert await _rows(db_session, RatedCharge) == []
    assert await _rows(db_session, BillingHold) == []
