"""Agent-facing feedback API (plan 046).

The machine — plugin-feedback inside a hosted Luna — authenticates with the
existing gateway tenant token (`Authorization: Bearer lsv1-…` or
`X-Luna-Gateway-Token`). `verify_token` resolves the Agent server-side, so a
caller can never name or read another agent's tickets: cross-agent ids return
404 (not 403 — don't leak existence).

Mounted at `/api/agent/feedback` and also under `/proxy` (machines carry
`LUNA_GATEWAY_URL = "<host>/proxy"`).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Header, HTTPException, Query, status
from sqlalchemy import func, select

from cloud.db import session as db_session
from cloud.db.models import Agent, FeedbackMessage, FeedbackTicket
from cloud.gateway import tokens as token_svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/feedback", tags=["feedback-agent"])

CATEGORIES = {"cost", "bug", "frustration", "feature", "praise", "other"}
SEVERITIES = {"low", "normal", "high"}
ORIGINS = {"user", "agent"}

# Rate limits per agent over the trailing 24h (plan 046). Enforced with a DB
# count, never an in-process counter — multiple uvicorn workers.
MAX_CREATES_PER_DAY = 30
MAX_REPLIES_PER_DAY = 120


def _as_uuid(ticket_id: str) -> uuid.UUID:
    """Parse a path id; a malformed id is a 404 (same as a missing one)."""
    try:
        return uuid.UUID(ticket_id)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")


def _bearer(authorization: str | None, x_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_token


async def _agent_from_token(authorization: str | None, x_token: str | None) -> Agent:
    token = _bearer(authorization, x_token)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing device token")
    async with db_session.get_session() as db:
        agent_id = await token_svc.verify_token(db, token)
        if agent_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid device token")
        agent = (await db.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown agent")
        return agent


def _aware(dt: datetime | None) -> datetime | None:
    """Postgres returns tz-aware datetimes; the SQLite test engine drops
    tzinfo. Normalize to UTC-aware so comparisons never mix naive/aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _unread(ticket: FeedbackTicket) -> bool:
    admin_at = _aware(ticket.last_admin_reply_at)
    if admin_at is None:
        return False
    read_at = _aware(ticket.agent_read_at)
    return read_at is None or admin_at > read_at


def _ticket_summary(t: FeedbackTicket) -> dict:
    return {
        "id": str(t.id),
        "title": t.title,
        "category": t.category,
        "origin": t.origin,
        "severity": t.severity,
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "last_admin_reply_at": (
            t.last_admin_reply_at.isoformat() if t.last_admin_reply_at else None
        ),
        "unread": _unread(t),
    }


def _message_view(m: FeedbackMessage) -> dict:
    return {
        "id": str(m.id),
        "author": m.author,
        "body": m.body,
        "meta": m.meta,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post("/tickets", status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)

    origin = (payload.get("origin") or "user").strip()
    category = (payload.get("category") or "other").strip()
    severity = (payload.get("severity") or "normal").strip()
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    if origin not in ORIGINS:
        raise HTTPException(422, "origin must be 'user' or 'agent'")
    if category not in CATEGORIES:
        raise HTTPException(422, f"category must be one of {sorted(CATEGORIES)}")
    if severity not in SEVERITIES:
        raise HTTPException(422, f"severity must be one of {sorted(SEVERITIES)}")
    if not title:
        raise HTTPException(422, "title required")
    if not body:
        raise HTTPException(422, "body required")

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    async with db_session.get_session() as db:
        recent = (await db.execute(
            select(func.count(FeedbackTicket.id)).where(
                FeedbackTicket.agent_id == agent.id,
                FeedbackTicket.created_at > day_ago,
            )
        )).scalar_one()
        if recent >= MAX_CREATES_PER_DAY:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Daily feedback ticket limit reached; try again later.",
            )

        # Client-supplied context under .client; server enrichment under
        # .server — keep both so drift is itself diagnostic (plan 046).
        server_ctx = {
            "slug": agent.slug,
            "image_version": agent.image_version,
            "runtime_ref": agent.runtime_ref,
        }
        context = {
            "client": payload.get("context") or {},
            "server": {k: v for k, v in server_ctx.items() if v is not None},
        }

        ticket = FeedbackTicket(
            agent_id=agent.id,
            account_id=agent.account_id,
            origin=origin,
            category=category,
            severity=severity,
            status="open",
            title=title[:200],
            context=context,
        )
        db.add(ticket)
        await db.flush()

        meta: dict = {}
        excerpt = payload.get("conversation_excerpt")
        if excerpt:
            meta["conversation_excerpt"] = excerpt
        technical = payload.get("technical")
        if technical:
            meta["technical"] = technical

        db.add(FeedbackMessage(
            ticket_id=ticket.id,
            author=origin,
            body=body,
            meta=meta or None,
        ))
        await db.commit()
        await db.refresh(ticket)
        return {
            "id": str(ticket.id),
            "status": ticket.status,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        }


@router.get("/tickets")
async def list_tickets(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    async with db_session.get_session() as db:
        rows = (await db.execute(
            select(FeedbackTicket)
            .where(FeedbackTicket.agent_id == agent.id)
            .order_by(FeedbackTicket.updated_at.desc())
            .limit(limit).offset(offset)
        )).scalars().all()
    return {"tickets": [_ticket_summary(t) for t in rows]}


@router.get("/updates")
async def updates(
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    """Cheap unread poll for prompt_sections(). Single agent-scoped query."""
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    async with db_session.get_session() as db:
        rows = (await db.execute(
            select(FeedbackTicket)
            .where(
                FeedbackTicket.agent_id == agent.id,
                FeedbackTicket.last_admin_reply_at.is_not(None),
                (FeedbackTicket.agent_read_at.is_(None))
                | (FeedbackTicket.last_admin_reply_at > FeedbackTicket.agent_read_at),
            )
            .order_by(FeedbackTicket.updated_at.desc())
        )).scalars().all()
    return {
        "unread": [
            {
                "id": str(t.id),
                "title": t.title,
                "last_admin_reply_at": (
                    t.last_admin_reply_at.isoformat() if t.last_admin_reply_at else None
                ),
            }
            for t in rows
        ]
    }


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    mark_read: int = Query(0),
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    tid = _as_uuid(ticket_id)
    async with db_session.get_session() as db:
        ticket = (await db.execute(
            select(FeedbackTicket).where(FeedbackTicket.id == tid)
        )).scalar_one_or_none()
        # 404 for another agent's ticket too — don't leak existence.
        if not ticket or ticket.agent_id != agent.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
        if mark_read:
            ticket.agent_read_at = datetime.now(timezone.utc)
        messages = (await db.execute(
            select(FeedbackMessage)
            .where(FeedbackMessage.ticket_id == ticket.id)
            .order_by(FeedbackMessage.created_at)
        )).scalars().all()
        result = {
            "ticket": {**_ticket_summary(ticket), "context": ticket.context},
            "messages": [_message_view(m) for m in messages],
        }
        await db.commit()
        return result


@router.post("/tickets/{ticket_id}/replies", status_code=status.HTTP_201_CREATED)
async def reply(
    ticket_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    author = (payload.get("author") or "user").strip()
    body = (payload.get("body") or "").strip()
    if author not in ORIGINS:
        raise HTTPException(422, "author must be 'user' or 'agent'")
    if not body:
        raise HTTPException(422, "body required")

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    tid = _as_uuid(ticket_id)

    async with db_session.get_session() as db:
        ticket = (await db.execute(
            select(FeedbackTicket).where(FeedbackTicket.id == tid)
        )).scalar_one_or_none()
        if not ticket or ticket.agent_id != agent.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")

        recent = (await db.execute(
            select(func.count(FeedbackMessage.id))
            .join(FeedbackTicket, FeedbackMessage.ticket_id == FeedbackTicket.id)
            .where(
                FeedbackTicket.agent_id == agent.id,
                FeedbackMessage.author.in_(("user", "agent")),
                FeedbackMessage.created_at > day_ago,
            )
        )).scalar_one()
        if recent >= MAX_REPLIES_PER_DAY:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Daily feedback reply limit reached; try again later.",
            )

        msg = FeedbackMessage(ticket_id=ticket.id, author=author, body=body)
        db.add(msg)
        ticket.last_client_reply_at = now
        # A client reply reopens the conversation for triage (also from closed).
        if ticket.status in ("answered", "closed"):
            ticket.status = "open"
            ticket.closed_at = None
        await db.flush()
        await db.refresh(msg)
        result = _message_view(msg)
        await db.commit()
        return result
