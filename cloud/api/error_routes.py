"""Admin-facing error tracking API (plan 051).

Cookie-authenticated, admin-only, same-origin guarded. Groups raw
`error_events` rows by fingerprint at query time — no pre-aggregation, so
grouping logic can evolve without touching stored data.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select

from cloud.auth.deps import enforce_same_origin, require_admin
from cloud.db import session as db_session
from cloud.db.models import Account, Agent, ErrorEvent, User

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/errors",
    tags=["errors"],
    dependencies=[Depends(enforce_same_origin)],
)

# critical > error > warning > info — max(rank) picks the group's worst.
_SEVERITY_RANK = case(
    (ErrorEvent.severity == "critical", 3),
    (ErrorEvent.severity == "error", 2),
    (ErrorEvent.severity == "warning", 1),
    else_=0,
)
_RANK_TO_SEVERITY = {3: "critical", 2: "error", 1: "warning", 0: "info"}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _event_view(e: ErrorEvent, agent: Agent | None, account: Account | None) -> dict:
    return {
        "id": str(e.id),
        "source": e.source,
        "kind": e.kind,
        "severity": e.severity,
        "message": e.message,
        "fingerprint": e.fingerprint,
        "context": e.context,
        "occurred_at": _iso(e.occurred_at),
        "created_at": _iso(e.created_at),
        "agent_id": str(e.agent_id) if e.agent_id else None,
        "agent_name": agent.name if agent else None,
        "agent_slug": agent.slug if agent else None,
        "account_id": str(e.account_id) if e.account_id else None,
        "account_slug": account.slug if account else None,
    }


def _base_filters(
    stmt,
    *,
    source: str | None,
    severity: str | None,
    kind: str | None,
    agent_id: str | None,
    account_id: str | None,
    q: str | None,
    since: datetime,
):
    stmt = stmt.where(ErrorEvent.created_at > since)
    if source:
        stmt = stmt.where(ErrorEvent.source == source)
    if severity:
        stmt = stmt.where(ErrorEvent.severity == severity)
    if kind:
        stmt = stmt.where(ErrorEvent.kind == kind)
    if agent_id:
        try:
            stmt = stmt.where(ErrorEvent.agent_id == uuid.UUID(agent_id))
        except ValueError:
            raise HTTPException(422, "agent_id must be a UUID")
    if account_id:
        try:
            stmt = stmt.where(ErrorEvent.account_id == uuid.UUID(account_id))
        except ValueError:
            raise HTTPException(422, "account_id must be a UUID")
    if q:
        stmt = stmt.where(
            or_(ErrorEvent.message.ilike(f"%{q}%"), ErrorEvent.kind.ilike(f"%{q}%"))
        )
    return stmt


@router.get("")
@router.get("/", include_in_schema=False)
async def list_groups(
    admin: User = Depends(require_admin),
    source: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    hours: int = Query(168, ge=1, le=24 * 90),
    sort: str = Query("last_seen"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Grouped list: one row per fingerprint with count + first/last seen."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = select(
        ErrorEvent.fingerprint,
        func.count(ErrorEvent.id).label("count"),
        func.min(ErrorEvent.created_at).label("first_seen"),
        func.max(ErrorEvent.created_at).label("last_seen"),
        func.count(func.distinct(ErrorEvent.agent_id)).label("agent_count"),
        func.max(_SEVERITY_RANK).label("severity_rank"),
        func.max(ErrorEvent.kind).label("kind"),
        func.max(ErrorEvent.source).label("source"),
        func.max(ErrorEvent.message).label("sample_message"),
    )
    stmt = _base_filters(
        stmt, source=source, severity=severity, kind=kind,
        agent_id=agent_id, account_id=account_id, q=q, since=since,
    ).group_by(ErrorEvent.fingerprint)
    order = func.count(ErrorEvent.id).desc() if sort == "count" \
        else func.max(ErrorEvent.created_at).desc()
    stmt = stmt.order_by(order).limit(limit).offset(offset)

    # Severity volume for the header chips — same filters, no grouping.
    totals_stmt = _base_filters(
        select(ErrorEvent.severity, func.count(ErrorEvent.id)),
        source=source, severity=severity, kind=kind,
        agent_id=agent_id, account_id=account_id, q=q, since=since,
    ).group_by(ErrorEvent.severity)

    async with db_session.get_session() as db:
        rows = (await db.execute(stmt)).all()
        totals = dict((await db.execute(totals_stmt)).all())

    return {
        "groups": [
            {
                "fingerprint": r.fingerprint,
                "count": r.count,
                "first_seen": _iso(r.first_seen),
                "last_seen": _iso(r.last_seen),
                "agent_count": r.agent_count,
                "severity": _RANK_TO_SEVERITY.get(r.severity_rank, "info"),
                "kind": r.kind,
                "source": r.source,
                "sample_message": r.sample_message,
            }
            for r in rows
        ],
        "totals_by_severity": {k: v for k, v in totals.items()},
    }


@router.get("/events/{event_id}")
async def get_event(event_id: str, admin: User = Depends(require_admin)):
    try:
        eid = uuid.UUID(event_id)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    async with db_session.get_session() as db:
        row = (await db.execute(
            select(ErrorEvent, Agent, Account)
            .join(Agent, ErrorEvent.agent_id == Agent.id, isouter=True)
            .join(Account, ErrorEvent.account_id == Account.id, isouter=True)
            .where(ErrorEvent.id == eid)
        )).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return {"event": _event_view(*row)}


@router.get("/{fingerprint}")
async def get_group(
    fingerprint: str,
    admin: User = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
):
    """A group's recent raw events, newest first, with full context."""
    async with db_session.get_session() as db:
        rows = (await db.execute(
            select(ErrorEvent, Agent, Account)
            .join(Agent, ErrorEvent.agent_id == Agent.id, isouter=True)
            .join(Account, ErrorEvent.account_id == Account.id, isouter=True)
            .where(ErrorEvent.fingerprint == fingerprint)
            .order_by(ErrorEvent.created_at.desc())
            .limit(limit)
        )).all()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return {"events": [_event_view(*r) for r in rows]}
