"""Background forwarder: drains relay_deliveries to tenant machines.

Each delivery is re-signed with the agent's derived relay secret (fresh
timestamp, preserved webhook-id) and POSTed to the machine's connector
ingress. Transient failures back off exponentially; hard rejections
dead-letter immediately.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from cloud.db.models import Agent, RelayDelivery
from cloud.db.session import get_session as get_db_session
from cloud.relay import standard_webhooks as sw
from cloud.relay.secrets import derive_relay_secret
from cloud.runtime.proxy_secret import derive_proxy_secret

log = logging.getLogger(__name__)

EVENTS_PATH = "/api/p/plugin-connectors/events/composio"
POLL_INTERVAL_S = 5
BATCH_SIZE = 20
MAX_ATTEMPTS = 10
BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 900
# 4xx that still deserve a retry (timeout-ish / throttling).
_RETRYABLE_4XX = (408, 429)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_BASE_S * (2 ** max(attempts - 1, 0)), BACKOFF_CAP_S))


async def _wake_if_needed(agent: Agent) -> None:
    if agent.status in ("stopped", "error"):
        try:
            from cloud.api.proxy import _try_wake_agent
            await _try_wake_agent(agent)
        except Exception:
            log.warning("relay: wake attempt failed for %s", agent.slug)


async def deliver_one(delivery_id: uuid.UUID, client: httpx.AsyncClient) -> None:
    """Attempt a single delivery; updates the row with the outcome."""
    async with get_db_session() as db:
        delivery = (await db.execute(
            select(RelayDelivery).where(RelayDelivery.id == delivery_id)
        )).scalar_one_or_none()
        if not delivery or delivery.status != "pending":
            return
        agent = (await db.execute(
            select(Agent).where(Agent.id == delivery.agent_id)
        )).scalar_one_or_none() if delivery.agent_id else None

        if agent is None or not agent.internal_url:
            delivery.status = "dead"
            delivery.last_error = "agent missing or has no internal_url"
            await db.commit()
            return
        body = delivery.body.encode()
        webhook_id = delivery.webhook_id
        agent_data = (agent.id, agent.slug, agent.internal_url, agent.runtime_ref, agent.status)

    agent_id, agent_slug, internal_url, runtime_ref, agent_status = agent_data

    root_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")
    headers = sw.sign(
        secret=derive_relay_secret(root_secret, str(agent_id)),
        webhook_id=webhook_id,
        body=body,
    )
    headers["content-type"] = "application/json"
    # Current hosted images gate every route behind the trusted-proxy check;
    # include the per-agent secret so delivery works before Luna's 007.003
    # verifier ships. Harmless after — it's this agent's own secret.
    headers["x-luna-proxy-secret"] = derive_proxy_secret(root_secret, str(agent_id))
    if runtime_ref:
        headers["fly-force-instance-id"] = runtime_ref

    status_code: int | None = None
    error: str | None = None
    try:
        resp = await client.post(f"{internal_url}{EVENTS_PATH}", content=body, headers=headers)
        status_code = resp.status_code
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}"
        # Machine may be asleep/dead — try waking for the next attempt.
        async with get_db_session() as db:
            agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if agent:
                await _wake_if_needed(agent)

    async with get_db_session() as db:
        delivery = (await db.execute(
            select(RelayDelivery).where(RelayDelivery.id == delivery_id)
        )).scalar_one()
        delivery.attempts += 1
        delivery.last_status_code = status_code
        delivery.last_error = error

        if status_code is not None and 200 <= status_code < 300:
            delivery.status = "delivered"
            delivery.delivered_at = _utcnow()
        elif (
            status_code is not None
            and 400 <= status_code < 500
            and status_code not in _RETRYABLE_4XX
        ):
            delivery.status = "dead"
            delivery.last_error = f"rejected with {status_code}"
            log.warning("relay: %s rejected delivery %s (%s)", agent_slug, webhook_id, status_code)
        elif delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = "dead"
            log.error("relay: dead-letter %s for %s after %d attempts", webhook_id, agent_slug, delivery.attempts)
        else:
            delivery.next_attempt_at = _utcnow() + _backoff(delivery.attempts)
        await db.commit()

    if status_code is not None and 200 <= status_code < 300:
        log.info("relay: delivered %s to %s (%s)", webhook_id, agent_slug, status_code)


async def run_pending_batch(client: httpx.AsyncClient) -> int:
    """Pick up due pending deliveries; returns number processed."""
    now = _utcnow()
    async with get_db_session() as db:
        ids = (await db.execute(
            select(RelayDelivery.id)
            .where(
                RelayDelivery.status == "pending",
                (RelayDelivery.next_attempt_at.is_(None)) | (RelayDelivery.next_attempt_at <= now),
            )
            .order_by(RelayDelivery.created_at)
            .limit(BATCH_SIZE)
        )).scalars().all()

    for delivery_id in ids:
        await deliver_one(delivery_id, client)
    return len(ids)


async def forwarder_loop() -> None:
    """Lifespan background task. Cancelled on shutdown."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10))
    log.info("relay forwarder started")
    try:
        while True:
            try:
                await run_pending_batch(client)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("relay forwarder cycle failed")
            await asyncio.sleep(POLL_INTERVAL_S)
    finally:
        await client.aclose()
