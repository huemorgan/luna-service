"""luna-control plan 002 phase 3 — chat index ingest, feed, unread, approvals, stream."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from cloud.chat import broker
from cloud.db.models import Agent, ChatEvent, ChatIndexRow
from cloud.gateway.tokens import issue_token

AGENT = "00000000-0000-0000-0000-000000000020"


async def _auth(db_session, agent):
    tok = await issue_token(db_session, agent.id)
    await db_session.commit()
    return {"Authorization": f"Bearer {tok}"}


def _msg(conv, role, text, at, eid=None, **kw):
    return {"type": "message", "event_id": eid or str(uuid.uuid4()), "conversation_id": conv,
            "message_id": str(uuid.uuid4()), "role": role, "created_at": at, "preview": text, **kw}


async def _post(client, headers, events):
    res = await client.post("/api/agent/chats/events", headers=headers, json={"events": events})
    assert res.status_code == 202, res.text
    return res.json()


@pytest.mark.asyncio
async def test_ingest_requires_token(anon_client):
    assert (await anon_client.post("/api/agent/chats/events", json={"events": []})).status_code == 401
    res = await anon_client.post("/api/agent/chats/events", headers={"Authorization": "Bearer lsv1-nope"}, json={"events": []})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_feed_orders_by_last_message_and_counts_unread(admin_client, db_session, sample_agent):
    h = await _auth(db_session, sample_agent)
    await _post(admin_client, h, [
        {"type": "conversation", "event_id": "c1", "conversation_id": "conv-a", "title": "Trip plan"},
        _msg("conv-a", "user", "book flights", "2026-09-26T10:00:00Z"),
        _msg("conv-a", "assistant", "Found 3 options", "2026-09-26T10:00:05Z"),
        _msg("conv-b", "assistant", "Daily digest ready", "2026-09-26T11:00:00Z", title="Digest"),
        _msg("conv-b", "assistant", "  second\n line  ", "2026-09-26T11:00:01Z"),
    ])
    res = await admin_client.get("/api/feed")
    assert res.status_code == 200
    items = res.json()["items"]
    assert [i["conversation_id"] for i in items] == ["conv-b", "conv-a"]
    b, a = items
    assert b["title"] == "Digest" and b["preview"] == "second line" and b["unread"] == 2
    assert a["title"] == "Trip plan" and a["last_role"] == "assistant" and a["unread"] == 1
    assert a["message_count"] == 2
    assert b["agent"]["slug"] == sample_agent.slug

    r = await admin_client.post(f"/api/feed/{AGENT}/conv-b/read")
    assert r.status_code == 204
    items = (await admin_client.get("/api/feed")).json()["items"]
    assert {i["conversation_id"]: i["unread"] for i in items} == {"conv-b": 0, "conv-a": 1}


@pytest.mark.asyncio
async def test_repeated_event_id_is_ignored(admin_client, db_session, sample_agent):
    h = await _auth(db_session, sample_agent)
    ev = _msg("conv-a", "assistant", "hi", "2026-09-26T10:00:00Z", eid="same")
    await _post(admin_client, h, [ev])
    await _post(admin_client, h, [ev])
    n = (await db_session.execute(select(func.count()).select_from(ChatEvent))).scalar()
    assert n == 1
    row = (await db_session.execute(select(ChatIndexRow))).scalar_one()
    assert row.message_count == 1


@pytest.mark.asyncio
async def test_approvals_pending_until_decided_even_without_conversation(admin_client, db_session, sample_agent):
    h = await _auth(db_session, sample_agent)
    await _post(admin_client, h, [
        _msg("conv-a", "assistant", "I need to send an email", "2026-09-26T10:00:00Z"),
        {"type": "approval.requested", "event_id": "r1", "approval_id": "ap-1", "conversation_id": "conv-a", "summary": "Send email"},
    ])
    items = (await admin_client.get("/api/feed")).json()["items"]
    assert items[0]["pending_approvals"] == 1
    # Decided from the Approvals list: no conversation id on the event.
    await _post(admin_client, h, [{"type": "approval.decided", "event_id": "d1", "approval_id": "ap-1", "decision": "approved"}])
    items = (await admin_client.get("/api/feed")).json()["items"]
    assert items[0]["pending_approvals"] == 0


@pytest.mark.asyncio
async def test_previews_off_keeps_metadata_only(admin_client, db_session, sample_agent):
    agent = await db_session.get(Agent, sample_agent.id)
    agent.chat_previews = False
    await db_session.commit()
    h = await _auth(db_session, sample_agent)
    await _post(admin_client, h, [_msg("conv-a", "assistant", "secret stuff", "2026-09-26T10:00:00Z")])
    item = (await admin_client.get("/api/feed")).json()["items"][0]
    assert item["preview"] is None and item["unread"] == 1
    assert (await db_session.execute(select(ChatIndexRow.preview))).scalar() is None


@pytest.mark.asyncio
async def test_deleted_conversation_leaves_feed(admin_client, db_session, sample_agent):
    h = await _auth(db_session, sample_agent)
    await _post(admin_client, h, [_msg("conv-a", "assistant", "hi", "2026-09-26T10:00:00Z")])
    await _post(admin_client, h, [{"type": "conversation.deleted", "event_id": "x", "conversation_id": "conv-a"}])
    assert (await admin_client.get("/api/feed")).json()["items"] == []


@pytest.mark.asyncio
async def test_junk_is_skipped_not_rejected(admin_client, db_session, sample_agent):
    h = await _auth(db_session, sample_agent)
    out = await _post(admin_client, h, ["nope", {"type": "weird"}, {"type": "message"}, None,
                                         _msg("c" * 500, "assistant", "x" * 5000, "not a date")])
    assert out["changed"] == 1
    row = (await db_session.execute(select(ChatIndexRow))).scalar_one()
    assert len(row.conversation_id) == 64 and len(row.preview) == 200


@pytest.mark.asyncio
async def test_feed_is_scoped_to_the_account(regular_client, admin_client, db_session, sample_agent):
    from cloud.auth.deps import clear_auth_cache
    clear_auth_cache()  # other tests leave cached memberships for these fixed ids
    h = await _auth(db_session, sample_agent)
    await _post(admin_client, h, [_msg("conv-a", "assistant", "hi", "2026-09-26T10:00:00Z")])
    res = await regular_client.get("/api/feed")
    assert res.status_code in (200, 403)
    if res.status_code == 200:
        assert res.json()["items"] == []
    assert (await regular_client.post(f"/api/feed/{AGENT}/conv-a/read")).status_code in (403, 404)


@pytest.mark.asyncio
async def test_ingest_publishes_change_to_subscribers(admin_client, db_session, sample_agent, account):
    h = await _auth(db_session, sample_agent)
    q = broker.subscribe(str(account.id))
    try:
        await _post(admin_client, h, [_msg("conv-a", "assistant", "hi", "2026-09-26T10:00:00Z")])
        change = await asyncio.wait_for(q.get(), timeout=1)
        assert change["agent_id"] == AGENT and change["conversations"] == ["conv-a"]
    finally:
        broker.unsubscribe(str(account.id), q)


@pytest.mark.asyncio
async def test_stream_route_is_member_only(anon_client):
    assert (await anon_client.get("/api/feed/stream")).status_code == 401
