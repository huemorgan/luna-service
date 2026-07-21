"""Agent-facing error ingest (plan 051; capture side is plan 007).

plugin-feedback inside a hosted Luna posts batches of error events with the
gateway tenant token (`Authorization: Bearer lsv1-…` or
`X-Luna-Gateway-Token`). Identity is resolved server-side from the token —
the client never sends agent/account ids and any it does send are ignored.

Fire-and-forget contract: always 202 on authenticated requests. Malformed
events are truncated or skipped, never 422'd; past the daily cap events are
dropped (logged), never 429'd — an error reporter that causes retry storms
would amplify the incident it is reporting.

Mounted at `/api/agent/errors` and also under `/proxy` (machines carry
`LUNA_GATEWAY_URL = "<host>/proxy"`).
"""

from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Header, HTTPException, status
from sqlalchemy import delete, func, select

from cloud.db import session as db_session
from cloud.db.models import Agent, ErrorEvent
from cloud.gateway import tokens as token_svc
from cloud.observability.error_sink import (
    SOURCES,
    clamp_kind,
    clamp_message,
    clamp_severity,
    compute_fingerprint,
    harden_context,
    parse_occurred_at,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/errors", tags=["errors-agent"])

MAX_BATCH = 50
# Errors are bursty; cap well above feedback's but still bounded. DB count,
# never an in-process counter — multiple uvicorn workers. Advisory: past the
# cap we drop (log only), no 429.
MAX_ERROR_EVENTS_PER_DAY = int(os.environ.get("MAX_ERROR_EVENTS_PER_DAY", "2000"))
ERROR_RETENTION_DAYS = int(os.environ.get("ERROR_RETENTION_DAYS", "60"))
# ~1% of accepted batches also run the retention delete — no scheduler needed.
PRUNE_PROBABILITY = 0.01


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


def _row_from_event(event: object, agent: Agent, now: datetime) -> ErrorEvent | None:
    """Harden one client event into a row; None = skip (never reject)."""
    if not isinstance(event, dict):
        return None
    source = event.get("source")
    if source not in SOURCES or source == "service":
        source = "agent"
    kind, original_kind = clamp_kind(event.get("kind"))
    message = clamp_message(event.get("message"))
    client_ctx = harden_context(event.get("context")) or {}
    if original_kind:
        client_ctx["original_kind"] = original_kind
    route = (
        client_ctx.get("route") or client_ctx.get("target") or client_ctx.get("url")
    )
    server_ctx = {
        "slug": agent.slug,
        "image_version": agent.image_version,
        "runtime_ref": agent.runtime_ref,
    }
    return ErrorEvent(
        source=source,
        agent_id=agent.id,
        account_id=agent.account_id,
        kind=kind,
        severity=clamp_severity(event.get("severity")),
        message=message,
        fingerprint=compute_fingerprint(kind, message, route if isinstance(route, str) else None),
        context={
            "client": client_ctx,
            "server": {k: v for k, v in server_ctx.items() if v is not None},
        },
        occurred_at=parse_occurred_at(event.get("occurred_at")) or now,
        created_at=now,
    )


async def _prune_expired(db) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=ERROR_RETENTION_DAYS)
    result = await db.execute(delete(ErrorEvent).where(ErrorEvent.created_at < cutoff))
    if result.rowcount:
        log.info("error retention pruned %d event(s) older than %dd",
                 result.rowcount, ERROR_RETENTION_DAYS)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
@router.post("/", status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
async def ingest_errors(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)

    events = payload.get("events")
    if not isinstance(events, list):
        events = []
    if len(events) > MAX_BATCH:
        events = events[:MAX_BATCH]

    now = datetime.now(timezone.utc)
    rows = [r for r in (_row_from_event(e, agent, now) for e in events) if r]
    if not rows:
        return {"accepted": 0}

    day_ago = now - timedelta(days=1)
    async with db_session.get_session() as db:
        recent = (await db.execute(
            select(func.count(ErrorEvent.id)).where(
                ErrorEvent.agent_id == agent.id,
                ErrorEvent.created_at > day_ago,
            )
        )).scalar_one()
        if recent >= MAX_ERROR_EVENTS_PER_DAY:
            log.warning(
                "error ingest: dropping %d event(s) from agent %s (daily cap %d)",
                len(rows), agent.slug, MAX_ERROR_EVENTS_PER_DAY,
            )
            return {"accepted": 0}
        # Partial headroom: keep the batch under the cap.
        headroom = MAX_ERROR_EVENTS_PER_DAY - recent
        if len(rows) > headroom:
            log.warning(
                "error ingest: truncating batch from agent %s to daily-cap headroom %d",
                agent.slug, headroom,
            )
            rows = rows[:headroom]

        db.add_all(rows)
        if random.random() < PRUNE_PROBABILITY:
            await _prune_expired(db)
        await db.commit()
    return {"accepted": len(rows)}
