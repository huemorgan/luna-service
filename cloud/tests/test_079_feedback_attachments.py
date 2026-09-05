"""Plan 079 — attachments as meta fields + honest timestamps.

The pane/tool sends `transcript` and `agent_context` as their own payload
fields; they land in the opening message's meta, elided from the default
agent read (token safety) but fully readable with include_attachments=1.
Reads never bump updated_at; last_activity_at tracks real changes only.
"""

from __future__ import annotations

import pytest

from datetime import datetime, timezone

from cloud.tests.test_feedback import _auth, _token

BIG = "x" * 10_000


def _instant(iso: str) -> datetime:
    """SQLite drops tzinfo while _aware() re-adds it — compare instants, not
    strings."""
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _create(anon_client, tok, **extra):
    res = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json={"title": "one line", "body": "the owner's actual words", **extra},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_attachments_stored_as_meta_fields(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    tid = await _create(
        anon_client, tok,
        transcript="[user]\nhello\n\n[assistant]\nhi",
        agent_context=BIG,
    )
    res = await anon_client.get(
        f"/api/agent/feedback/tickets/{tid}?include_attachments=1", headers=_auth(tok)
    )
    assert res.status_code == 200
    opening = res.json()["messages"][0]
    # the body stays the owner's words — attachments never leak into it
    assert opening["body"] == "the owner's actual words"
    assert opening["meta"]["transcript"].startswith("[user]")
    assert opening["meta"]["agent_context"] == BIG


@pytest.mark.asyncio
async def test_big_attachments_elided_by_default(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    tid = await _create(anon_client, tok, agent_context=BIG, transcript="short")
    res = await anon_client.get(
        f"/api/agent/feedback/tickets/{tid}", headers=_auth(tok)
    )
    meta = res.json()["messages"][0]["meta"]
    assert meta["agent_context"] == {
        "elided": True, "chars": 10_000,
        "note": "re-fetch this ticket with include_attachments=1 for the full text",
    }
    assert meta["transcript"] == "short"  # small ones stay inline


@pytest.mark.asyncio
async def test_attachments_clamped_server_side(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    tid = await _create(anon_client, tok, agent_context="y" * 250_000)
    res = await anon_client.get(
        f"/api/agent/feedback/tickets/{tid}?include_attachments=1", headers=_auth(tok)
    )
    assert len(res.json()["messages"][0]["meta"]["agent_context"]) == 200_000


@pytest.mark.asyncio
async def test_mark_read_does_not_bump_updated_at(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    tid = await _create(anon_client, tok)
    before = (await anon_client.get(
        "/api/agent/feedback/tickets", headers=_auth(tok)
    )).json()["tickets"][0]["updated_at"]

    res = await anon_client.get(
        f"/api/agent/feedback/tickets/{tid}?mark_read=1", headers=_auth(tok)
    )
    assert res.status_code == 200

    after = (await anon_client.get(
        "/api/agent/feedback/tickets", headers=_auth(tok)
    )).json()["tickets"][0]
    assert after["updated_at"] == before


@pytest.mark.asyncio
async def test_last_activity_tracks_replies_not_reads(
    anon_client, admin_client, db_session, sample_agent
):
    tok = await _token(db_session, sample_agent)
    tid = await _create(anon_client, tok)

    row = (await anon_client.get(
        "/api/agent/feedback/tickets", headers=_auth(tok)
    )).json()["tickets"][0]
    assert _instant(row["last_activity_at"]) == _instant(row["created_at"])

    reply = await admin_client.post(
        f"/api/admin/feedback/tickets/{tid}/reply", json={"body": "answered"}
    )
    assert reply.status_code == 201

    # agent read must not move last_activity_at past the reply
    await anon_client.get(
        f"/api/agent/feedback/tickets/{tid}?mark_read=1", headers=_auth(tok)
    )
    row = (await anon_client.get(
        "/api/agent/feedback/tickets", headers=_auth(tok)
    )).json()["tickets"][0]
    assert _instant(row["last_activity_at"]) == _instant(row["last_admin_reply_at"])

    admin_row = (await admin_client.get(
        "/api/admin/feedback/tickets"
    )).json()["tickets"][0]
    assert _instant(admin_row["last_activity_at"]) == _instant(row["last_admin_reply_at"])
