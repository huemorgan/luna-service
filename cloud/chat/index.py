"""Chat index for the Luna iPhone app (luna-control plan 002, phase 3).

Every event source (a Luna pushing events, or a tenant-DB trigger listener) calls
`apply_events` with the same small event dicts:

    {"type": "message", "event_id", "conversation_id", "message_id", "role",
     "created_at", "preview"?, "title"?}
    {"type": "conversation", "event_id", "conversation_id", "title"?, "kind"?, "state"?}
    {"type": "conversation.deleted", "event_id", "conversation_id"}
    {"type": "approval.requested", "event_id", "approval_id", "conversation_id"?, "summary"?}
    {"type": "approval.decided", "event_id", "approval_id", "conversation_id"?, "decision"?}
    {"type": "turn.started", "event_id", "conversation_id", "source"?}
    {"type": "turn.ended", "event_id", "conversation_id", "error_code"?}

Inputs are untrusted: unknown types are skipped, strings are clamped, and a repeated
`event_id` is ignored. Nothing here ever raises back at the sender.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select

from cloud.db.models import Agent, ChatEvent, ChatIndexRow, ChatReadMarker

log = logging.getLogger(__name__)

TYPES = {
    "message", "conversation", "conversation.deleted",
    "approval.requested", "approval.decided", "turn.started", "turn.ended",
}
PREVIEW_CHARS = 200
TITLE_CHARS = 200
ID_CHARS = 64
RETENTION_DAYS = 30
# A turn whose "ended" never arrived (machine crash) stops showing as working after this.
WORKING_STALE = timedelta(minutes=10)


def _s(v: object, n: int) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s[:n] if s else None


def _when(v: object, now: datetime) -> datetime:
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            # A skewed clock can't push a chat above everything else for long.
            return min(d, now + timedelta(minutes=5))
        except ValueError:
            pass
    return now


def _preview(v: object) -> str | None:
    s = _s(v, PREVIEW_CHARS * 4)
    if not s:
        return None
    s = " ".join(s.split())
    return s if len(s) <= PREVIEW_CHARS else s[: PREVIEW_CHARS - 1] + "…"


async def apply_events(db, agent: Agent, events: list) -> set[str]:
    """Store events and update the index. Returns the conversation ids that changed.
    The caller commits (and notifies feed listeners after the commit)."""
    now = datetime.now(timezone.utc)
    changed: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") not in TYPES:
            continue
        typ = ev["type"]
        event_id = _s(ev.get("event_id"), ID_CHARS) or str(uuid.uuid4())
        seen = (await db.execute(select(ChatEvent.id).where(
            ChatEvent.agent_id == agent.id, ChatEvent.event_id == event_id,
        ))).first()
        if seen:
            continue

        conv = _s(ev.get("conversation_id"), ID_CHARS)
        approval = _s(ev.get("approval_id"), ID_CHARS)
        if typ == "approval.decided" and not conv and approval:
            # A decision made from the Approvals list carries no conversation; take it from the request.
            conv = (await db.execute(select(ChatEvent.conversation_id).where(
                ChatEvent.agent_id == agent.id,
                ChatEvent.approval_id == approval,
                ChatEvent.type == "approval.requested",
            ))).scalar()
        if typ not in ("approval.requested", "approval.decided") and not conv:
            continue

        when = _when(ev.get("created_at") or ev.get("occurred_at"), now)
        role = _s(ev.get("role"), 16)
        preview = _preview(ev.get("preview")) if agent.chat_previews else None
        payload = {k: v for k, v in {
            "message_id": _s(ev.get("message_id"), ID_CHARS),
            "summary": _preview(ev.get("summary")) if agent.chat_previews else None,
            "decision": _s(ev.get("decision"), 32),
            "error_code": _s(ev.get("error_code"), 64),
        }.items() if v is not None}
        db.add(ChatEvent(
            agent_id=agent.id, event_id=event_id, type=typ, conversation_id=conv,
            approval_id=approval, role=role, occurred_at=when, payload=payload or None,
        ))

        if not conv:
            continue
        changed.add(conv)
        row = await db.get(ChatIndexRow, (agent.id, conv))
        if typ == "conversation.deleted":
            if row:
                await db.delete(row)
            continue
        if row is None:
            row = ChatIndexRow(agent_id=agent.id, conversation_id=conv, message_count=0)
            db.add(row)
        if typ == "message":
            if row.last_message_at is None or when >= row.last_message_at:
                row.last_message_at = when
                row.last_role = role
                row.preview = preview
            row.message_count = (row.message_count or 0) + 1
        if "title" in ev and _s(ev.get("title"), TITLE_CHARS):
            row.title = _s(ev.get("title"), TITLE_CHARS)
        if typ == "conversation":
            row.kind = _s(ev.get("kind"), 32) or row.kind
            row.state = _s(ev.get("state"), 32) or row.state
            # A new, empty chat sorts by its creation time; the first message replaces it.
            if row.last_message_at is None and (ev.get("created_at") or ev.get("occurred_at")):
                row.last_message_at = when
        row.updated_at = now
    await db.flush()
    return changed


async def prune(db) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    await db.execute(delete(ChatEvent).where(ChatEvent.created_at < cutoff))


async def feed(db, user_id: uuid.UUID, account_id: uuid.UUID, since: datetime | None = None) -> list[dict]:
    """Every indexed conversation on the account's Lunas, newest first, with this
    person's unread count and the pending approvals."""
    agents = {a.id: a for a in (await db.execute(select(Agent).where(
        Agent.account_id == account_id, Agent.deleted_at.is_(None),
    ))).scalars()}
    if not agents:
        return []
    q = select(ChatIndexRow).where(ChatIndexRow.agent_id.in_(agents))
    if since:
        q = q.where(ChatIndexRow.updated_at > since)
    rows = (await db.execute(q)).scalars().all()

    markers = {
        (m.agent_id, m.conversation_id): m.last_read_at
        for m in (await db.execute(select(ChatReadMarker).where(
            ChatReadMarker.user_id == user_id, ChatReadMarker.agent_id.in_(agents),
        ))).scalars()
    }
    unread = await _unread(db, rows, markers)
    pending = await _pending(db, list(agents))
    working = await _working(db, list(agents))

    out = []
    for r in rows:
        a = agents[r.agent_id]
        out.append({
            "agent": {"id": str(a.id), "slug": a.slug, "name": a.name, "color": a.color, "status": a.status},
            "conversation_id": r.conversation_id,
            "title": r.title,
            "kind": r.kind,
            "state": r.state,
            "last_message_at": _iso(r.last_message_at),
            "last_role": r.last_role,
            "preview": r.preview if a.chat_previews else None,
            "message_count": r.message_count,
            "unread": unread.get((r.agent_id, r.conversation_id), 0),
            "pending_approvals": pending.get((r.agent_id, r.conversation_id), 0),
            "working": (r.agent_id, r.conversation_id) in working,
            "updated_at": _iso(r.updated_at),
        })
    far = datetime.min.replace(tzinfo=timezone.utc)
    out.sort(key=lambda x: _aware(_last(x)) or far, reverse=True)
    return out


def _last(item: dict) -> datetime | None:
    v = item.get("last_message_at")
    return datetime.fromisoformat(v) if v else None


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime | None) -> str | None:
    d = _aware(d)
    return d.isoformat() if d else None


async def _unread(db, rows, markers) -> dict:
    """Assistant messages newer than the person's read marker (or all of them, unread
    since forever, capped by retention)."""
    if not rows:
        return {}
    conds = []
    for r in rows:
        read_at = markers.get((r.agent_id, r.conversation_id))
        c = and_(ChatEvent.agent_id == r.agent_id, ChatEvent.conversation_id == r.conversation_id)
        if read_at is not None:
            c = and_(c, ChatEvent.occurred_at > read_at)
        conds.append(c)
    res = await db.execute(
        select(ChatEvent.agent_id, ChatEvent.conversation_id, func.count())
        .where(ChatEvent.type == "message", ChatEvent.role == "assistant", or_(*conds))
        .group_by(ChatEvent.agent_id, ChatEvent.conversation_id)
    )
    return {(a, c): n for a, c, n in res.all()}


async def _pending(db, agent_ids: list) -> dict:
    """Approvals requested with no decision yet, per conversation."""
    decided = select(ChatEvent.approval_id).where(
        ChatEvent.agent_id.in_(agent_ids), ChatEvent.type == "approval.decided",
    )
    res = await db.execute(
        select(ChatEvent.agent_id, ChatEvent.conversation_id, func.count())
        .where(
            ChatEvent.agent_id.in_(agent_ids),
            ChatEvent.type == "approval.requested",
            ChatEvent.conversation_id.is_not(None),
            ChatEvent.approval_id.not_in(decided),
        )
        .group_by(ChatEvent.agent_id, ChatEvent.conversation_id)
    )
    return {(a, c): n for a, c, n in res.all()}


async def _working(db, agent_ids: list) -> set:
    """Conversations whose latest turn event is a start, within WORKING_STALE."""
    cutoff = datetime.now(timezone.utc) - WORKING_STALE
    res = await db.execute(
        select(ChatEvent.agent_id, ChatEvent.conversation_id, ChatEvent.type, ChatEvent.occurred_at)
        .where(
            ChatEvent.agent_id.in_(agent_ids),
            ChatEvent.type.in_(("turn.started", "turn.ended")),
            ChatEvent.occurred_at > cutoff,
        )
        .order_by(ChatEvent.occurred_at, ChatEvent.created_at)
    )
    latest: dict = {}
    for a, c, typ, _ in res.all():
        latest[(a, c)] = typ
    return {k for k, typ in latest.items() if typ == "turn.started"}


async def mark_read(db, user_id: uuid.UUID, agent_id: uuid.UUID, conversation_id: str) -> None:
    now = datetime.now(timezone.utc)
    m = await db.get(ChatReadMarker, (user_id, agent_id, conversation_id))
    if m is None:
        db.add(ChatReadMarker(user_id=user_id, agent_id=agent_id,
                              conversation_id=conversation_id, last_read_at=now))
    else:
        m.last_read_at = now
