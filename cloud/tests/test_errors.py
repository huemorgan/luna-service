"""Plan 051 — error tracking: fingerprinting, agent ingest, sink, admin API."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from cloud.db.models import Agent, ErrorEvent
from cloud.gateway.tokens import issue_token
from cloud.observability import error_sink
from cloud.observability.error_sink import (
    clamp_kind,
    clamp_severity,
    compute_fingerprint,
    harden_context,
    record_error_event,
)


async def _token(db_session, agent):
    tok = await issue_token(db_session, agent.id)
    await db_session.commit()
    return tok


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(autouse=True)
def _reset_sink_state():
    error_sink._buckets.clear()
    error_sink._dropped = 0
    error_sink._last_drop_log = 0.0
    yield
    error_sink._buckets.clear()


# ── Fingerprint normalization ────────────────────────────────────────────────

def test_fingerprint_normalizes_ids_and_numbers():
    a = compute_fingerprint(
        "fetch_error",
        "GET /api/tasks/3f9b2c1e-1111-2222-3333-444455556666 failed with 502",
        "/a/my-agent/api/tasks/3f9b2c1e-1111-2222-3333-444455556666",
    )
    b = compute_fingerprint(
        "fetch_error",
        "GET /api/tasks/aaaaaaaa-bbbb-cccc-dddd-eeeeffff0000 failed with 502",
        "/a/my-agent/api/tasks/aaaaaaaa-bbbb-cccc-dddd-eeeeffff0000",
    )
    assert a == b


def test_fingerprint_differs_by_kind_and_message():
    base = compute_fingerprint("js_error", "TypeError: x is undefined", "/pane/tasks")
    assert base != compute_fingerprint("fetch_error", "TypeError: x is undefined", "/pane/tasks")
    assert base != compute_fingerprint("js_error", "ReferenceError: y is not defined", "/pane/tasks")
    # Numbers normalize; distinct words don't.
    assert compute_fingerprint("timeout", "waited 8123 ms") == compute_fingerprint("timeout", "waited 9001 ms")


def test_clamps():
    assert clamp_kind("js_error") == ("js_error", None)
    assert clamp_kind("weird_thing") == ("agent_report", "weird_thing")
    assert clamp_severity("critical") == "critical"
    assert clamp_severity("nonsense") == "error"
    ctx = harden_context({"stack": "x" * 20000, "breadcrumbs": list(range(50))})
    assert len(ctx["stack"]) <= error_sink.MAX_STACK_CHARS + 20
    assert len(ctx["breadcrumbs"]) == error_sink.MAX_BREADCRUMBS


# ── Agent ingest ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_requires_token(anon_client):
    res = await anon_client.post("/api/agent/errors", json={"events": []})
    assert res.status_code == 401
    res = await anon_client.post(
        "/api/agent/errors", headers=_auth("lsv1-bogus"), json={"events": []}
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_ingest_batch_enriches_server_side(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    res = await anon_client.post(
        "/api/agent/errors",
        headers=_auth(tok),
        json={"events": [
            {
                "source": "ui",
                "kind": "js_error",
                "severity": "error",
                "message": "TypeError: x is undefined",
                "occurred_at": "2026-07-20T12:00:00Z",
                # identity from the client must be ignored
                "agent_id": str(uuid.uuid4()),
                "context": {"url": "/pane/tasks", "stack": "at foo()"},
            },
            {"kind": "plugin_exception", "message": "boom", "severity": "warning"},
        ]},
    )
    assert res.status_code == 202, res.text
    assert res.json()["accepted"] == 2

    rows = (await db_session.execute(
        select(ErrorEvent).order_by(ErrorEvent.kind)
    )).scalars().all()
    assert len(rows) == 2
    js = next(r for r in rows if r.kind == "js_error")
    assert js.source == "ui"
    assert js.agent_id == sample_agent.id
    assert js.account_id == sample_agent.account_id
    assert js.fingerprint and len(js.fingerprint) == 40
    assert js.context["client"]["url"] == "/pane/tasks"
    assert js.context["server"]["slug"] == sample_agent.slug
    assert js.occurred_at is not None
    other = next(r for r in rows if r.kind == "plugin_exception")
    assert other.source == "agent" and other.severity == "warning"


@pytest.mark.asyncio
async def test_ingest_hardens_never_rejects(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    res = await anon_client.post(
        "/api/agent/errors",
        headers=_auth(tok),
        json={"events": [
            {"kind": "totally_unknown", "severity": "apocalyptic",
             "message": "m" * 5000, "context": {"stack": "s" * 50000}},
            "not-a-dict",
            {"kind": "js_error"},  # no message
        ]},
    )
    assert res.status_code == 202
    assert res.json()["accepted"] == 2  # the string entry is skipped

    rows = (await db_session.execute(select(ErrorEvent))).scalars().all()
    weird = next(r for r in rows if r.context["client"].get("original_kind"))
    assert weird.kind == "agent_report"
    assert weird.context["client"]["original_kind"] == "totally_unknown"
    assert weird.severity == "error"
    assert len(weird.message) <= error_sink.MAX_MESSAGE_CHARS
    no_msg = next(r for r in rows if r.kind == "js_error")
    assert no_msg.message == "(no message)"


@pytest.mark.asyncio
async def test_ingest_batch_cap(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    events = [{"kind": "js_error", "message": f"e{i}"} for i in range(80)]
    res = await anon_client.post(
        "/api/agent/errors", headers=_auth(tok), json={"events": events}
    )
    assert res.status_code == 202
    assert res.json()["accepted"] == 50


@pytest.mark.asyncio
async def test_ingest_daily_cap_drops_silently(anon_client, db_session, sample_agent, monkeypatch):
    from cloud.api import error_agent_routes
    monkeypatch.setattr(error_agent_routes, "MAX_ERROR_EVENTS_PER_DAY", 3)
    tok = await _token(db_session, sample_agent)

    res = await anon_client.post(
        "/api/agent/errors", headers=_auth(tok),
        json={"events": [{"kind": "timeout", "message": f"t{i}"} for i in range(5)]},
    )
    assert res.status_code == 202
    assert res.json()["accepted"] == 3  # truncated to headroom

    res = await anon_client.post(
        "/api/agent/errors", headers=_auth(tok),
        json={"events": [{"kind": "timeout", "message": "more"}]},
    )
    assert res.status_code == 202
    assert res.json()["accepted"] == 0  # capped, dropped, never 429

    count = (await db_session.execute(select(func.count(ErrorEvent.id)))).scalar_one()
    assert count == 3


@pytest.mark.asyncio
async def test_ingest_under_proxy_prefix(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    res = await anon_client.post(
        "/proxy/api/agent/errors", headers=_auth(tok),
        json={"events": [{"kind": "llm_timeout", "message": "llm timed out"}]},
    )
    assert res.status_code == 202
    assert res.json()["accepted"] == 1


# ── Service sink ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sink_writes_service_row(_patch_db, db_session):
    await record_error_event(
        kind="proxy_502", severity="error", message="Cannot reach Luna instance",
        route="/a/test-agent/api/health", context={"method": "GET"},
    )
    row = (await db_session.execute(select(ErrorEvent))).scalar_one()
    assert row.source == "service"
    assert row.kind == "proxy_502"
    assert row.agent_id is None
    assert row.fingerprint


@pytest.mark.asyncio
async def test_sink_throttles_per_fingerprint(_patch_db, db_session):
    for _ in range(30):
        await record_error_event(kind="proxy_502", message="same thing", route="/a/x")
    count = (await db_session.execute(select(func.count(ErrorEvent.id)))).scalar_one()
    assert count == error_sink._THROTTLE_PER_MIN


@pytest.mark.asyncio
async def test_sink_never_raises_without_db():
    # No _patch_db: the session factory points at an unreachable engine config.
    await record_error_event(kind="timeout", message="db is down")  # must not raise


@pytest.mark.asyncio
async def test_unhandled_exception_recorded(_patch_db, db_session, monkeypatch):
    # Starlette re-raises after the Exception handler runs, so use a client
    # that doesn't propagate app exceptions to see the wire response.
    from httpx import ASGITransport, AsyncClient

    from cloud.api import proxy as proxy_mod
    from cloud.main import create_app

    async def _boom(request, agent_slug):  # noqa: ARG001
        raise RuntimeError("kaboom")

    monkeypatch.setattr(proxy_mod, "_resolve_agent", _boom)
    app = create_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/a/some-agent/", headers={"accept": "text/html"})
    assert res.status_code == 500
    row = (await db_session.execute(
        select(ErrorEvent).where(ErrorEvent.kind == "unhandled_exception")
    )).scalar_one()
    assert "kaboom" in row.message
    assert row.severity == "critical"


# ── Admin API ────────────────────────────────────────────────────────────────

async def _seed_events(anon_client, db_session, agent):
    tok = await _token(db_session, agent)
    await anon_client.post(
        "/api/agent/errors", headers=_auth(tok),
        json={"events": [
            {"kind": "js_error", "severity": "error",
             "message": "TypeError: x is undefined", "source": "ui",
             "context": {"url": "/pane/tasks", "stack": "at foo()"}},
            {"kind": "js_error", "severity": "error",
             "message": "TypeError: x is undefined", "source": "ui",
             "context": {"url": "/pane/tasks"}},
            {"kind": "llm_timeout", "severity": "critical",
             "message": "model call timed out", "source": "agent"},
        ]},
    )


@pytest.mark.asyncio
async def test_admin_groups_and_detail(admin_client, anon_client, db_session, sample_agent):
    await _seed_events(anon_client, db_session, sample_agent)

    res = await admin_client.get("/api/admin/errors")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["groups"]) == 2
    by_kind = {g["kind"]: g for g in body["groups"]}
    assert by_kind["js_error"]["count"] == 2
    assert by_kind["js_error"]["source"] == "ui"
    assert by_kind["llm_timeout"]["severity"] == "critical"
    assert body["totals_by_severity"]["error"] == 2

    fp = by_kind["js_error"]["fingerprint"]
    res = await admin_client.get(f"/api/admin/errors/{fp}")
    assert res.status_code == 200
    events = res.json()["events"]
    assert len(events) == 2
    assert events[0]["agent_slug"] == sample_agent.slug
    assert events[0]["account_slug"] == "test-account"

    eid = events[0]["id"]
    res = await admin_client.get(f"/api/admin/errors/events/{eid}")
    assert res.status_code == 200
    assert res.json()["event"]["id"] == eid


@pytest.mark.asyncio
async def test_admin_filters(admin_client, anon_client, db_session, sample_agent):
    await _seed_events(anon_client, db_session, sample_agent)

    res = await admin_client.get("/api/admin/errors", params={"severity": "critical"})
    groups = res.json()["groups"]
    assert len(groups) == 1 and groups[0]["kind"] == "llm_timeout"

    res = await admin_client.get("/api/admin/errors", params={"source": "ui"})
    assert {g["kind"] for g in res.json()["groups"]} == {"js_error"}

    res = await admin_client.get("/api/admin/errors", params={"q": "timed out"})
    assert {g["kind"] for g in res.json()["groups"]} == {"llm_timeout"}

    res = await admin_client.get(
        "/api/admin/errors", params={"agent_id": str(sample_agent.id)}
    )
    assert len(res.json()["groups"]) == 2


@pytest.mark.asyncio
async def test_admin_errors_require_admin(regular_client, anon_client):
    res = await regular_client.get("/api/admin/errors")
    assert res.status_code in (401, 403)
    res = await anon_client.get("/api/admin/errors")
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_group_404(admin_client):
    res = await admin_client.get("/api/admin/errors/deadbeef" * 5)
    assert res.status_code == 404
    res = await admin_client.get(f"/api/admin/errors/events/{uuid.uuid4()}")
    assert res.status_code == 404
