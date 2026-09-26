"""Chat feed for the Luna iPhone app (luna-control plan 002, phase 3).

Member side (session cookie or X-Luna-Session):
  GET  /api/feed                               every chat across the account's Lunas
  GET  /api/feed/stream                        SSE: `ready`, then `feed` on each change
  POST /api/feed/{agent_id}/{conversation_id}/read

Agent side (gateway tenant token, same auth as /api/agent/errors):
  POST /api/agent/chats/events                 {"events": [...]} (see cloud.chat.index)

The ingest is fire-and-forget like the error ingest: always 202 when authenticated,
malformed events are skipped, never 4xx'd.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from cloud.api.error_agent_routes import _agent_from_token
from cloud.auth.deps import require_active_account
from cloud.chat import broker, index
from cloud.db import session as db_session
from cloud.db.models import Account, Agent, User

router = APIRouter(prefix="/api/feed", tags=["feed"])
agent_router = APIRouter(prefix="/api/agent/chats", tags=["feed-agent"])

MAX_BATCH = 200
PRUNE_PROBABILITY = 0.01
HEARTBEAT_SECONDS = 15


@router.get("")
async def get_feed(since: str | None = None, auth: tuple[User, Account] = Depends(require_active_account)):
    user, account = auth
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(400, "invalid since") from e
    async with db_session.get_session() as db:
        return {"items": await index.feed(db, user.id, account.id, since_dt)}


@router.post("/{agent_id}/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(agent_id: uuid.UUID, conversation_id: str,
                    auth: tuple[User, Account] = Depends(require_active_account)):
    user, account = auth
    async with db_session.get_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None or agent.account_id != account.id or agent.deleted_at is not None:
            raise HTTPException(404, "Unknown agent")
        await index.mark_read(db, user.id, agent_id, conversation_id[:64])
        await broker.notify(db, str(account.id), str(agent_id), {conversation_id[:64]})
        await db.commit()


@router.get("/stream")
async def stream(request: Request, auth: tuple[User, Account] = Depends(require_active_account)):
    _, account = auth
    key = str(account.id)

    async def events():
        q = broker.subscribe(key)
        try:
            yield "event: ready\ndata: {}\n\n"
            while not await request.is_disconnected():
                try:
                    change = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                body = {"agent_id": change.get("agent_id"), "conversations": change.get("conversations", [])}
                yield f"event: feed\ndata: {json.dumps(body)}\n\n"
        finally:
            broker.unsubscribe(key, q)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@agent_router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
    x_luna_gateway_token: str | None = Header(default=None),
):
    agent = await _agent_from_token(authorization, x_luna_gateway_token)
    events = payload.get("events")
    if not isinstance(events, list):
        return {"accepted": 0}
    events = events[:MAX_BATCH]
    async with db_session.get_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
        changed = await index.apply_events(db, agent, events)
        if changed:
            await broker.notify(db, str(agent.account_id), str(agent.id), changed)
        if random.random() < PRUNE_PROBABILITY:
            await index.prune(db)
        await db.commit()
    return {"accepted": len(events), "changed": len(changed)}
