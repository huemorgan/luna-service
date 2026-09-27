"""Fan-out of feed changes to open `/api/feed/stream` connections.

Ingest can land on either uvicorn worker, and the phone's stream can be held by the
other. On Postgres the ingest transaction issues `pg_notify('chat_feed', …)`; every
worker keeps one LISTEN connection on luna-service's own database and hands each
notification to its local subscribers. That is one connection per worker, not per
Luna. Elsewhere (SQLite tests) `publish_local` is called directly after commit.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import text

log = logging.getLogger(__name__)

CHANNEL = "chat_feed"
_subscribers: dict[str, set[asyncio.Queue]] = {}


def subscribe(account_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.setdefault(account_id, set()).add(q)
    return q


def unsubscribe(account_id: str, q: asyncio.Queue) -> None:
    subs = _subscribers.get(account_id)
    if subs:
        subs.discard(q)
        if not subs:
            _subscribers.pop(account_id, None)


def publish_local(account_id: str, change: dict) -> None:
    for q in list(_subscribers.get(account_id, ())):
        try:
            q.put_nowait(change)
        except asyncio.QueueFull:
            pass  # a stalled client re-fetches the feed when it reconnects


async def notify(db, account_id: str, agent_id: str, conversations: set[str]) -> None:
    """Call inside the ingest transaction; delivery happens on commit."""
    change = {"account_id": account_id, "agent_id": agent_id, "conversations": sorted(conversations)[:50]}
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": json.dumps(change)})
    else:
        publish_local(account_id, change)


async def listen_loop(database_url: str) -> None:
    """One LISTEN connection per worker; reconnects with backoff. Missed changes while
    down are harmless: clients re-fetch the feed on (re)connect."""
    import asyncpg

    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")

    def on_notify(_conn, _pid, _channel, payload: str) -> None:
        try:
            change = json.loads(payload)
            publish_local(change["account_id"], change)
        except Exception:  # noqa: BLE001
            log.warning("chat_feed: bad notification payload")

    backoff = 1
    while True:
        conn = None
        try:
            conn = await asyncpg.connect(dsn)
            await conn.add_listener(CHANNEL, on_notify)
            backoff = 1
            while not conn.is_closed():
                await asyncio.sleep(30)
                await conn.execute("SELECT 1")  # keeps the idle connection alive through Render's LB
        except asyncio.CancelledError:
            if conn is not None:
                await conn.close()
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("chat_feed listener: %s", exc)
        if conn is not None and not conn.is_closed():
            await conn.close()
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)
