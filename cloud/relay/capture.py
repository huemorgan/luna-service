"""Extract Composio connected-account ids — from webhook payloads and from
gateway-proxied Composio API responses (mapping capture).

Composio payload shapes vary across API versions, so extraction is
deliberately tolerant: it walks the JSON looking for the well-known key
spellings instead of assuming one schema.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import ComposioAccountLink

log = logging.getLogger(__name__)

_ACCOUNT_ID_KEYS = {
    "connected_account_id", "connectedaccountid", "connected_account_nano_id",
    "connectedaccountnanoid",
}
_APP_KEYS = {"app_name", "appname", "app_unique_id", "appuniqueid", "toolkit_slug", "toolkit"}

# Response objects that ARE a connected account use a plain "id"/"nanoid" —
# only trust those when the object also self-identifies via these keys.
_ACCOUNT_OBJECT_MARKERS = {"appuniqueid", "app_unique_id", "authconfig", "auth_config", "toolkit"}

MAX_CAPTURE_BYTES = 1_000_000


def _walk(node, found: list[tuple[str, str | None]]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, found)
        return
    if not isinstance(node, dict):
        return

    lowered = {k.lower().replace("-", "_"): v for k, v in node.items()}
    app = None
    for key in _APP_KEYS:
        val = lowered.get(key)
        if isinstance(val, str) and val:
            app = val.lower()
            break

    for key in _ACCOUNT_ID_KEYS:
        val = lowered.get(key)
        if isinstance(val, str) and val:
            found.append((val, app))

    if _ACCOUNT_OBJECT_MARKERS & lowered.keys():
        for id_key in ("id", "nanoid", "nano_id"):
            val = lowered.get(id_key)
            if isinstance(val, str) and val:
                found.append((val, app))
                break

    for value in node.values():
        _walk(value, found)


def extract_connected_accounts(payload) -> list[tuple[str, str | None]]:
    """Return [(connected_account_id, app_name|None), …], deduped, order kept."""
    found: list[tuple[str, str | None]] = []
    _walk(payload, found)
    seen: set[str] = set()
    out = []
    for acc_id, app in found:
        if acc_id not in seen:
            seen.add(acc_id)
            out.append((acc_id, app))
    return out


def extract_event_account(payload) -> str | None:
    """The single connected account a webhook event belongs to (first match)."""
    accounts = extract_connected_accounts(payload)
    return accounts[0][0] if accounts else None


async def upsert_links(
    db: AsyncSession,
    agent_id: uuid.UUID,
    accounts: list[tuple[str, str | None]],
    *,
    source: str = "gateway",
) -> int:
    """Insert/update links for an agent. Returns number of rows touched."""
    now = datetime.now(timezone.utc)
    count = 0
    for acc_id, app in accounts:
        existing = (await db.execute(
            select(ComposioAccountLink).where(
                ComposioAccountLink.connected_account_id == acc_id
            )
        )).scalar_one_or_none()
        if existing:
            existing.agent_id = agent_id
            existing.last_seen_at = now
            if app and not existing.app_name:
                existing.app_name = app
        else:
            db.add(ComposioAccountLink(
                connected_account_id=acc_id,
                agent_id=agent_id,
                app_name=app,
                source=source,
                last_seen_at=now,
            ))
        count += 1
    await db.flush()
    return count


async def capture_from_gateway_response(
    agent_id: uuid.UUID, content_type: str, body: bytes,
) -> None:
    """Best-effort mapping capture from a proxied Composio response.

    Called after the response finished streaming. Must never raise into the
    proxy path — same contract as usage metering.
    """
    if "json" not in content_type or not body or len(body) > MAX_CAPTURE_BYTES:
        return
    try:
        payload = json.loads(body)
    except Exception:
        return
    accounts = extract_connected_accounts(payload)
    if not accounts:
        return
    try:
        from cloud.db import session as db_session
        async with db_session.get_session() as db:
            n = await upsert_links(db, agent_id, accounts, source="gateway")
            await db.commit()
        log.info("composio capture: agent=%s linked %d account(s)", agent_id, n)
    except Exception:
        log.exception("composio capture failed (agent=%s)", agent_id)
