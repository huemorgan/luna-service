"""Plan 046 — feedback tickets: agent self-service + admin triage."""

from __future__ import annotations

import uuid

import pytest

from cloud.db.models import Account, Agent
from cloud.gateway.tokens import issue_token


async def _token(db_session, agent):
    tok = await issue_token(db_session, agent.id)
    await db_session.commit()
    return tok


async def _second_agent(db_session, account, admin_user):
    agent = Agent(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000b2"),
        account_id=account.id,
        creator_id=admin_user.id,
        name="Second Agent",
        slug="test-account-second-agent",
        status="running",
        image_version="0.01.001",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── Agent API ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_creates_ticket_and_lists(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    res = await anon_client.post(
        "/api/agent/feedback/tickets",
        headers=_auth(tok),
        json={
            "origin": "agent",
            "category": "frustration",
            "severity": "high",
            "title": "Owner is frustrated with repeated failures",
            "body": "The owner said this keeps failing and is useless.",
            "context": {"agent_name": "Test Agent", "mission": "help"},
            "technical": {"error": "tool X raised TimeoutError"},
        },
    )
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["id"] and created["status"] == "open" and created["created_at"]

    listing = (await anon_client.get(
        "/api/agent/feedback/tickets", headers=_auth(tok)
    )).json()
    assert len(listing["tickets"]) == 1
    t = listing["tickets"][0]
    assert t["origin"] == "agent" and t["category"] == "frustration"
    assert t["unread"] is False


@pytest.mark.asyncio
async def test_agent_create_requires_token(anon_client):
    res = await anon_client.post("/api/agent/feedback/tickets", json={"title": "x", "body": "y"})
    assert res.status_code == 401
    res = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth("lsv1-bogus"),
        json={"title": "x", "body": "y"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_agent_create_validates(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    r = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"category": "nope", "title": "t", "body": "b"},
    )
    assert r.status_code == 422
    r = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"title": "", "body": "b"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_ticket_and_context_enrichment(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    tid = (await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"title": "t", "body": "b", "context": {"agent_name": "Test Agent"},
              "conversation_excerpt": [{"role": "user", "content": "hi"}]},
    )).json()["id"]

    got = (await anon_client.get(
        f"/api/agent/feedback/tickets/{tid}?mark_read=1", headers=_auth(tok)
    )).json()
    assert got["ticket"]["id"] == tid
    # server enrichment present alongside the client block
    assert got["ticket"]["context"]["server"]["slug"] == sample_agent.slug
    assert got["ticket"]["context"]["client"]["agent_name"] == "Test Agent"
    # opening message carries the excerpt in meta
    assert got["messages"][0]["meta"]["conversation_excerpt"][0]["content"] == "hi"


@pytest.mark.asyncio
async def test_cross_agent_ticket_is_404(anon_client, db_session, sample_agent, account, admin_user):
    tok_a = await _token(db_session, sample_agent)
    tid = (await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok_a),
        json={"title": "secret", "body": "b"},
    )).json()["id"]

    agent_b = await _second_agent(db_session, account, admin_user)
    tok_b = await _token(db_session, agent_b)

    # cross-agent GET → 404, not 403 (no existence leak)
    res = await anon_client.get(
        f"/api/agent/feedback/tickets/{tid}", headers=_auth(tok_b)
    )
    assert res.status_code == 404
    # and agent B's list does not include A's ticket
    listing = (await anon_client.get(
        "/api/agent/feedback/tickets", headers=_auth(tok_b)
    )).json()
    assert listing["tickets"] == []


@pytest.mark.asyncio
async def test_proxy_prefix_alias(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    res = await anon_client.post(
        "/proxy/api/agent/feedback/tickets", headers=_auth(tok),
        json={"title": "via proxy", "body": "b"},
    )
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_client_reply_reopens(anon_client, admin_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    tid = (await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"title": "t", "body": "b"},
    )).json()["id"]

    # admin answers → status answered
    ar = await admin_client.post(f"/api/admin/feedback/tickets/{tid}/reply", json={"body": "we hear you"})
    assert ar.status_code == 201
    got = (await anon_client.get(f"/api/agent/feedback/tickets/{tid}", headers=_auth(tok))).json()
    assert got["ticket"]["status"] == "answered"

    # client reply reopens
    rr = await anon_client.post(
        f"/api/agent/feedback/tickets/{tid}/replies", headers=_auth(tok),
        json={"author": "user", "body": "thanks, still broken"},
    )
    assert rr.status_code == 201
    got = (await anon_client.get(f"/api/agent/feedback/tickets/{tid}", headers=_auth(tok))).json()
    assert got["ticket"]["status"] == "open"


@pytest.mark.asyncio
async def test_updates_reports_unread(anon_client, admin_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    tid = (await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"title": "unread-me", "body": "b"},
    )).json()["id"]

    # no admin reply yet → nothing unread
    assert (await anon_client.get("/api/agent/feedback/updates", headers=_auth(tok))).json()["unread"] == []

    await admin_client.post(f"/api/admin/feedback/tickets/{tid}/reply", json={"body": "hi"})
    unread = (await anon_client.get("/api/agent/feedback/updates", headers=_auth(tok))).json()["unread"]
    assert len(unread) == 1 and unread[0]["id"] == tid

    # reading it (mark_read) clears the unread poll
    await anon_client.get(f"/api/agent/feedback/tickets/{tid}?mark_read=1", headers=_auth(tok))
    assert (await anon_client.get("/api/agent/feedback/updates", headers=_auth(tok))).json()["unread"] == []


@pytest.mark.asyncio
async def test_create_rate_limit(anon_client, db_session, sample_agent, monkeypatch):
    import cloud.api.feedback_agent_routes as far
    monkeypatch.setattr(far, "MAX_CREATES_PER_DAY", 2)
    tok = await _token(db_session, sample_agent)
    for _ in range(2):
        r = await anon_client.post(
            "/api/agent/feedback/tickets", headers=_auth(tok),
            json={"title": "t", "body": "b"},
        )
        assert r.status_code == 201
    r = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"title": "t", "body": "b"},
    )
    assert r.status_code == 429


# ── Admin API ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_requires_admin(regular_client, admin_client, anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"title": "t", "body": "b"},
    )
    assert (await regular_client.get("/api/admin/feedback/tickets")).status_code == 403
    assert (await admin_client.get("/api/admin/feedback/tickets")).status_code == 200


@pytest.mark.asyncio
async def test_admin_list_join_and_filters(admin_client, anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"origin": "agent", "category": "cost", "title": "too expensive", "body": "b"},
    )
    data = (await admin_client.get("/api/admin/feedback/tickets")).json()
    assert len(data["tickets"]) == 1
    row = data["tickets"][0]
    assert row["agent_slug"] == sample_agent.slug
    assert row["account_slug"] == "test-account"
    assert row["origin"] == "agent"

    # category filter
    assert len((await admin_client.get("/api/admin/feedback/tickets?category=cost")).json()["tickets"]) == 1
    assert len((await admin_client.get("/api/admin/feedback/tickets?category=bug")).json()["tickets"]) == 0
    # search by title
    assert len((await admin_client.get("/api/admin/feedback/tickets?q=expensive")).json()["tickets"]) == 1


@pytest.mark.asyncio
async def test_admin_reply_and_close_reopen(admin_client, anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    tid = (await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"title": "t", "body": "b"},
    )).json()["id"]

    # admin reply → answered, message authored by admin
    r = await admin_client.post(f"/api/admin/feedback/tickets/{tid}/reply", json={"body": "on it"})
    assert r.status_code == 201 and r.json()["author"] == "admin"
    detail = (await admin_client.get(f"/api/admin/feedback/tickets/{tid}")).json()
    assert detail["ticket"]["status"] == "answered"
    assert any(m["author"] == "admin" for m in detail["messages"])

    # close then a client reply reopens
    cr = await admin_client.post(f"/api/admin/feedback/tickets/{tid}/status", json={"status": "closed"})
    assert cr.json()["status"] == "closed"
    await anon_client.post(
        f"/api/agent/feedback/tickets/{tid}/replies", headers=_auth(tok),
        json={"author": "user", "body": "reopen please"},
    )
    detail = (await admin_client.get(f"/api/admin/feedback/tickets/{tid}")).json()
    assert detail["ticket"]["status"] == "open"


@pytest.mark.asyncio
async def test_admin_list_newest_first_and_unread_badge(admin_client, anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    ids = []
    for i in range(3):
        ids.append((await anon_client.post(
            "/api/agent/feedback/tickets", headers=_auth(tok),
            json={"title": f"t{i}", "body": "b"},
        )).json()["id"])

    # newest first
    listed = [t["id"] for t in (await admin_client.get("/api/admin/feedback/tickets")).json()["tickets"]]
    assert listed == list(reversed(ids))

    # all three unread until the team opens them
    assert (await admin_client.get("/api/admin/feedback/unread-count")).json()["unread"] == 3
    await admin_client.get(f"/api/admin/feedback/tickets/{ids[0]}")
    assert (await admin_client.get("/api/admin/feedback/unread-count")).json()["unread"] == 2
    row = next(t for t in (await admin_client.get("/api/admin/feedback/tickets")).json()["tickets"] if t["id"] == ids[0])
    assert row["unread_by_us"] is False and row["admin_read_at"]

    # replying marks read too
    await admin_client.post(f"/api/admin/feedback/tickets/{ids[1]}/reply", json={"body": "hi"})
    assert (await admin_client.get("/api/admin/feedback/unread-count")).json()["unread"] == 1

    # a client reply on a read ticket makes it unread again
    await anon_client.post(
        f"/api/agent/feedback/tickets/{ids[0]}/replies", headers=_auth(tok),
        json={"author": "user", "body": "more"},
    )
    assert (await admin_client.get("/api/admin/feedback/unread-count")).json()["unread"] == 2

    # closed tickets don't count
    await admin_client.post(f"/api/admin/feedback/tickets/{ids[2]}/status", json={"status": "closed"})
    assert (await admin_client.get("/api/admin/feedback/unread-count")).json()["unread"] == 1


@pytest.mark.asyncio
async def test_admin_ticket_404(admin_client):
    res = await admin_client.get(f"/api/admin/feedback/tickets/{uuid.uuid4()}")
    assert res.status_code == 404
