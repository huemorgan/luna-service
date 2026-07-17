"""Admin-facing feedback triage API (plan 046).

Cookie-authenticated, admin-only, same-origin guarded. Lists/answers tickets
across all agents from the luna-service admin Feedback page. Ticket bodies and
conversation excerpts are owner content — admin-only, no export endpoint.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select

from cloud.auth.deps import enforce_same_origin, require_admin
from cloud.db import session as db_session
from cloud.db.models import Account, Agent, FeedbackMessage, FeedbackTicket, User

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/feedback",
    tags=["feedback"],
    dependencies=[Depends(enforce_same_origin)],
)


def _as_uuid(ticket_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(ticket_id)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")


class ReplyBody(BaseModel):
    body: str


class StatusBody(BaseModel):
    status: str


def _ticket_row(t: FeedbackTicket, agent: Agent | None, account: Account | None) -> dict:
    # "unread by us" = the client (owner/agent) spoke after the team last did.
    unread_by_us = t.last_client_reply_at is not None and (
        t.last_admin_reply_at is None or t.last_client_reply_at > t.last_admin_reply_at
    )
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
        "last_client_reply_at": (
            t.last_client_reply_at.isoformat() if t.last_client_reply_at else None
        ),
        "unread_by_us": unread_by_us,
        "agent_name": agent.name if agent else None,
        "agent_slug": agent.slug if agent else None,
        "account_slug": account.slug if account else None,
    }


def _message_view(m: FeedbackMessage) -> dict:
    return {
        "id": str(m.id),
        "author": m.author,
        "admin_user_id": str(m.admin_user_id) if m.admin_user_id else None,
        "body": m.body,
        "meta": m.meta,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/tickets")
async def list_tickets(
    admin: User = Depends(require_admin),
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    origin: str | None = Query(default=None),
    agent: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    async with db_session.get_session() as db:
        stmt = (
            select(FeedbackTicket, Agent, Account)
            .join(Agent, FeedbackTicket.agent_id == Agent.id, isouter=True)
            .join(Account, Agent.account_id == Account.id, isouter=True)
        )
        if status_filter:
            stmt = stmt.where(FeedbackTicket.status == status_filter)
        if category:
            stmt = stmt.where(FeedbackTicket.category == category)
        if origin:
            stmt = stmt.where(FeedbackTicket.origin == origin)
        if agent:
            stmt = stmt.where(
                or_(Agent.slug == agent, Agent.name.ilike(f"%{agent}%"))
            )
        if q:
            stmt = stmt.where(FeedbackTicket.title.ilike(f"%{q}%"))

        # Unanswered-first: open before answered before closed; within a group,
        # oldest updated first (FIFO triage).
        status_rank = case(
            (FeedbackTicket.status == "open", 0),
            (FeedbackTicket.status == "answered", 1),
            else_=2,
        )
        stmt = stmt.order_by(status_rank, FeedbackTicket.updated_at).limit(limit).offset(offset)
        rows = (await db.execute(stmt)).all()
    return {"tickets": [_ticket_row(t, ag, ac) for (t, ag, ac) in rows]}


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, admin: User = Depends(require_admin)):
    async with db_session.get_session() as db:
        row = (await db.execute(
            select(FeedbackTicket, Agent, Account)
            .join(Agent, FeedbackTicket.agent_id == Agent.id, isouter=True)
            .join(Account, Agent.account_id == Account.id, isouter=True)
            .where(FeedbackTicket.id == _as_uuid(ticket_id))
        )).first()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
        ticket, agent, account = row
        messages = (await db.execute(
            select(FeedbackMessage)
            .where(FeedbackMessage.ticket_id == ticket.id)
            .order_by(FeedbackMessage.created_at)
        )).scalars().all()
    return {
        "ticket": {**_ticket_row(ticket, agent, account), "context": ticket.context},
        "messages": [_message_view(m) for m in messages],
    }


@router.post("/tickets/{ticket_id}/reply", status_code=status.HTTP_201_CREATED)
async def reply(
    ticket_id: str,
    payload: ReplyBody,
    request: Request,
    admin: User = Depends(require_admin),
):
    body = payload.body.strip()
    if not body:
        raise HTTPException(422, "body required")
    now = datetime.now(timezone.utc)
    async with db_session.get_session() as db:
        ticket = (await db.execute(
            select(FeedbackTicket).where(FeedbackTicket.id == _as_uuid(ticket_id))
        )).scalar_one_or_none()
        if not ticket:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
        msg = FeedbackMessage(
            ticket_id=ticket.id,
            author="admin",
            admin_user_id=admin.id,
            body=body,
        )
        db.add(msg)
        ticket.last_admin_reply_at = now
        ticket.status = "answered"
        await db.flush()
        await db.refresh(msg)
        result = _message_view(msg)
        await db.commit()
        return result


@router.post("/tickets/{ticket_id}/status")
async def set_status(
    ticket_id: str,
    payload: StatusBody,
    admin: User = Depends(require_admin),
):
    new_status = payload.status.strip()
    if new_status not in ("open", "closed"):
        raise HTTPException(422, "status must be 'open' or 'closed'")
    async with db_session.get_session() as db:
        ticket = (await db.execute(
            select(FeedbackTicket).where(FeedbackTicket.id == _as_uuid(ticket_id))
        )).scalar_one_or_none()
        if not ticket:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
        ticket.status = new_status
        ticket.closed_at = datetime.now(timezone.utc) if new_status == "closed" else None
        await db.commit()
        return {"id": str(ticket.id), "status": ticket.status}
