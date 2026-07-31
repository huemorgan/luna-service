"""Admin-facing error tracking API (plan 051).

Cookie-authenticated, admin-only, same-origin guarded. Groups raw
`error_events` rows by fingerprint at query time — no pre-aggregation, so
grouping logic can evolve without touching stored data.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select

from cloud.auth.deps import enforce_same_origin, require_admin
from cloud.db import session as db_session
from cloud.db.models import Account, Agent, ErrorEvent, ErrorGroupStatus, User

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

# Effective triage status, derived at query time (plan 065). "regressed"
# means resolved but events arrived after resolved_at — deliberately never
# stored, so the ingest hot path stays write-only. Requires the grouped
# ErrorEvent join, since it compares against max(created_at).
_EFFECTIVE_STATUS = case(
    (func.coalesce(ErrorGroupStatus.status, "open") == "open", "open"),
    (func.max(ErrorEvent.created_at) > ErrorGroupStatus.resolved_at, "regressed"),
    else_="resolved",
)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything here is UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _effective_status(row: ErrorGroupStatus | None, last_seen: datetime | None) -> str:
    """Python twin of _EFFECTIVE_STATUS for single-group views."""
    if row is None or row.status == "open":
        return "open"
    resolved_at, last_seen = _aware(row.resolved_at), _aware(last_seen)
    if resolved_at and last_seen and last_seen > resolved_at:
        return "regressed"
    return "resolved"


def _status_view(row: ErrorGroupStatus | None, last_seen: datetime | None,
                 resolved_by_email: str | None = None) -> dict:
    return {
        "status": _effective_status(row, last_seen),
        "note": row.note if row else None,
        "resolved_at": _iso(row.resolved_at) if row else None,
        "resolved_by_email": resolved_by_email,
    }


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
    status_f: str | None = Query(default=None, alias="status"),
):
    """Grouped list: one row per fingerprint with count + first/last seen."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    grouped = select(
        ErrorEvent.fingerprint,
        func.count(ErrorEvent.id).label("count"),
        func.min(ErrorEvent.created_at).label("first_seen"),
        func.max(ErrorEvent.created_at).label("last_seen"),
        func.count(func.distinct(ErrorEvent.agent_id)).label("agent_count"),
        func.max(_SEVERITY_RANK).label("severity_rank"),
        func.max(ErrorEvent.kind).label("kind"),
        func.max(ErrorEvent.source).label("source"),
        func.max(ErrorEvent.message).label("sample_message"),
        _EFFECTIVE_STATUS.label("status"),
        ErrorGroupStatus.note.label("note"),
        ErrorGroupStatus.resolved_at.label("resolved_at"),
        ErrorGroupStatus.resolved_by.label("resolved_by"),
    ).join(
        ErrorGroupStatus,
        ErrorGroupStatus.fingerprint == ErrorEvent.fingerprint,
        isouter=True,
    )
    # Status columns are functionally dependent on the fingerprint PK, but
    # grouped explicitly so the query is valid on any backend.
    grouped = _base_filters(
        grouped, source=source, severity=severity, kind=kind,
        agent_id=agent_id, account_id=account_id, q=q, since=since,
    ).group_by(
        ErrorEvent.fingerprint, ErrorGroupStatus.fingerprint,
        ErrorGroupStatus.status, ErrorGroupStatus.note,
        ErrorGroupStatus.resolved_at, ErrorGroupStatus.resolved_by,
    ).subquery()

    # Filter on the derived status outside the aggregation so limit/offset
    # paginate the filtered set. "active" = open + regressed (the UI default).
    stmt = select(grouped)
    if status_f == "active":
        stmt = stmt.where(grouped.c.status != "resolved")
    elif status_f in ("open", "resolved", "regressed"):
        stmt = stmt.where(grouped.c.status == status_f)
    elif status_f:
        raise HTTPException(422, "status must be open|resolved|regressed|active")
    order = grouped.c.count.desc() if sort == "count" else grouped.c.last_seen.desc()
    stmt = stmt.order_by(order).limit(limit).offset(offset)

    # Group counts per effective status, unfiltered by status_f — the header
    # shows the full triage picture regardless of the current tab.
    status_totals_stmt = select(grouped.c.status, func.count()).group_by(grouped.c.status)

    # Severity volume for the header chips — same filters, no grouping.
    totals_stmt = _base_filters(
        select(ErrorEvent.severity, func.count(ErrorEvent.id)),
        source=source, severity=severity, kind=kind,
        agent_id=agent_id, account_id=account_id, q=q, since=since,
    ).group_by(ErrorEvent.severity)

    async with db_session.get_session() as db:
        rows = (await db.execute(stmt)).all()
        totals = dict((await db.execute(totals_stmt)).all())
        status_totals = dict((await db.execute(status_totals_stmt)).all())
        resolver_ids = {r.resolved_by for r in rows if r.resolved_by}
        emails: dict = {}
        if resolver_ids:
            emails = dict((await db.execute(
                select(User.id, User.email).where(User.id.in_(resolver_ids))
            )).all())

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
                "status": r.status,
                "note": r.note,
                "resolved_at": _iso(r.resolved_at),
                "resolved_by_email": emails.get(r.resolved_by),
            }
            for r in rows
        ],
        "totals_by_severity": {k: v for k, v in totals.items()},
        "totals_by_status": {
            s: status_totals.get(s, 0) for s in ("open", "resolved", "regressed")
        },
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


class StatusUpdate(BaseModel):
    status: Literal["open", "resolved"]
    note: str | None = Field(default=None, max_length=1000)


@router.put("/{fingerprint}/status")
async def set_group_status(
    fingerprint: str,
    body: StatusUpdate,
    admin: User = Depends(require_admin),
):
    """Upsert a group's triage state. Resolving stamps resolved_at/by, so a
    later event makes the group read as regressed; re-resolving a regressed
    group just moves resolved_at forward. Reopening clears both."""
    now = datetime.now(timezone.utc)
    async with db_session.get_session() as db:
        known = (await db.execute(
            select(ErrorEvent.id).where(ErrorEvent.fingerprint == fingerprint).limit(1)
        )).first()
        if not known:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")

        row = await db.get(ErrorGroupStatus, fingerprint)
        if row is None:
            row = ErrorGroupStatus(fingerprint=fingerprint, created_at=now)
            db.add(row)
        row.status = body.status
        row.note = body.note
        if body.status == "resolved":
            row.resolved_at = now
            row.resolved_by = admin.id
        else:
            row.resolved_at = None
            row.resolved_by = None
        row.updated_at = now

        last_seen = (await db.execute(
            select(func.max(ErrorEvent.created_at))
            .where(ErrorEvent.fingerprint == fingerprint)
        )).scalar()
        view = _status_view(row, last_seen, admin.email if body.status == "resolved" else None)
        await db.commit()
    return {"group_status": view}


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
        status_row = await db.get(ErrorGroupStatus, fingerprint)
        resolver_email = None
        if status_row and status_row.resolved_by:
            resolver_email = (await db.execute(
                select(User.email).where(User.id == status_row.resolved_by)
            )).scalar()
    last_seen = rows[0][0].created_at
    return {
        "events": [_event_view(*r) for r in rows],
        "group_status": _status_view(status_row, last_seen, resolver_email),
    }
