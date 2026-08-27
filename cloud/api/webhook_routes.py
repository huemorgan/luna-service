"""Public generic webhook ingress (plan 076).

ANY /api/webhooks/hooks/{agent_slug}/{hook_slug} — external systems call the
minted URL; we deliver to the tenant machine's plugin route.

sync mode (default): forward the raw body inline with standard-webhooks HMAC
headers signed with the per-hook secret, wake the machine on transport error,
poll readiness, retry once, and return the machine's response verbatim (so
provider challenge handshakes work).

queue mode: wrap the request in a JSON envelope (HMAC inside), insert a
relay_deliveries outbox row with the hook's target_path, return 202; the
plan-015 forwarder delivers with backoff/dead-letter and wake-on-sleep.

Auth model (plan 035 D3): slug knowledge only at the edge; the plugin
verifies the per-hook HMAC. Hosted machines additionally gate every route
behind the per-agent x-luna-proxy-secret, which both paths include.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac as hmac_mod
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from cloud.db.models import Agent, RelayDelivery, WebhookEndpoint
from cloud.db.session import get_session as get_db_session
from cloud.relay import standard_webhooks as sw
from cloud.runtime.proxy_secret import derive_proxy_secret

log = logging.getLogger(__name__)

relay_router = APIRouter(tags=["webhooks-relay"])

MAX_BODY = 200 * 1024
RELAY_TIMEOUT_S = 120.0  # a hook can start a long agent turn on a cold machine
READY_MAX_WAIT_S = 45.0
READY_POLL_S = 2.0

# Request headers never forwarded to the machine.
# accept-encoding: Fly's edge compresses per this header (br since 2026-08-27),
# and httpx here may not be able to decode what the *caller* accepts — the
# response would pass through as raw brotli with the content-encoding header
# dropped, corrupting sync-mode echoes (Monday challenge). Let httpx negotiate
# only encodings it can decode.
_DROP_HEADERS = {
    "host", "content-length", "connection", "transfer-encoding", "keep-alive",
    "upgrade", "proxy-authorization", "authorization", "cookie",
    "accept-encoding",
}


def _forward_headers(request: Request) -> dict[str, str]:
    out = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in _DROP_HEADERS or lk.startswith(("x-luna-", "fly-", "webhook-")):
            continue
        out[lk] = v
    return out


async def _wait_machine_ready(agent: Agent, client: httpx.AsyncClient) -> bool:
    """Poll the machine's /api/health after a wake until it answers (≤45 s).

    Closes the cold-start gap: _try_wake_agent returns as soon as fly.start()
    does, well before uvicorn inside the machine is listening.
    """
    if not agent.internal_url:
        return False
    headers = {}
    if agent.runtime_ref:
        headers["fly-force-instance-id"] = agent.runtime_ref
    deadline = time.monotonic() + READY_MAX_WAIT_S
    url = f"{agent.internal_url.rstrip('/')}/api/health"
    while time.monotonic() < deadline:
        try:
            resp = await client.get(url, headers=headers, timeout=httpx.Timeout(3, connect=2))
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        await asyncio.sleep(READY_POLL_S)
    return False


async def _bump_stats(endpoint_id, status_code: int | None) -> None:
    try:
        async with get_db_session() as db:
            ep = (await db.execute(
                select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id)
            )).scalar_one_or_none()
            if ep:
                ep.delivery_count += 1
                ep.last_delivery_at = datetime.now(timezone.utc)
                ep.last_status_code = status_code
                await db.commit()
    except Exception:  # noqa: BLE001 — stats must never fail a delivery
        log.warning("webhooks: stats update failed for %s", endpoint_id)


@relay_router.api_route(
    "/api/webhooks/hooks/{agent_slug}/{hook_slug}", methods=["GET", "POST"]
)
async def webhook_ingress(agent_slug: str, hook_slug: str, request: Request):
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.slug == agent_slug)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown hook")
        endpoint = (await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.hook_slug == hook_slug,
                WebhookEndpoint.agent_id == agent.id,
            )
        )).scalar_one_or_none()
        if not endpoint:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown hook")
        if not endpoint.enabled:
            raise HTTPException(status.HTTP_410_GONE, "Hook disabled")

    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Payload too large")

    if endpoint.mode == "queue":
        return await _enqueue(endpoint, agent, request, raw)
    return await _deliver_sync(endpoint, agent, request, raw)


async def _deliver_sync(
    endpoint: WebhookEndpoint, agent: Agent, request: Request, raw: bytes
) -> Response:
    if not (agent.internal_url or "").startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent has no machine")

    root_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")
    headers = _forward_headers(request)
    headers.update(sw.sign(
        secret=endpoint.secret,
        webhook_id=f"hook_{uuid.uuid4().hex[:16]}",
        body=raw,
    ))
    headers["x-luna-hook-name"] = endpoint.name
    headers["x-luna-hook-plugin"] = endpoint.plugin
    headers["x-luna-proxy-secret"] = derive_proxy_secret(root_secret, str(agent.id))
    if agent.runtime_ref:
        headers["fly-force-instance-id"] = agent.runtime_ref

    target = f"{(agent.internal_url or '').rstrip('/')}{endpoint.target_path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    method = request.method.upper()

    async def _send(client: httpx.AsyncClient):
        return await client.request(method, target, content=raw or None, headers=headers)

    async with httpx.AsyncClient(timeout=httpx.Timeout(RELAY_TIMEOUT_S, connect=10)) as client:
        try:
            resp = await _send(client)
        except httpx.ReadTimeout:
            # NOT retried — the sender retries and the plugin dedupes, so a
            # slow agent turn can't be double-run (scheduler relay precedent).
            await _bump_stats(endpoint.id, 504)
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Agent turn timed out")
        except httpx.HTTPError:
            # Machine asleep/unreachable — wake, wait until ready, retry once.
            from cloud.api.proxy import _try_wake_agent

            if not await _try_wake_agent(agent):
                await _bump_stats(endpoint.id, 502)
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Agent unreachable")
            await _wait_machine_ready(agent, client)
            try:
                resp = await _send(client)
            except httpx.HTTPError:
                await _bump_stats(endpoint.id, 502)
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY, "Agent unreachable after wake"
                )

    await _bump_stats(endpoint.id, resp.status_code)
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


async def _enqueue(
    endpoint: WebhookEndpoint, agent: Agent, request: Request, raw: bytes
) -> Response:
    try:
        body_text = raw.decode("utf-8")
        body_b64 = None
    except UnicodeDecodeError:
        body_text = None
        body_b64 = base64.b64encode(raw).decode("ascii")

    envelope = json.dumps({
        "hook": endpoint.name,
        "hook_slug": endpoint.hook_slug,
        "plugin": endpoint.plugin,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "method": request.method.upper(),
        "query": str(request.url.query or ""),
        "headers": _forward_headers(request),
        "body": body_text,
        "body_b64": body_b64,
        # Plugin-verifiable proof the control plane accepted this for the
        # named hook: HMAC of the raw body with the per-hook secret.
        "signature": hmac_mod.new(
            endpoint.secret.encode(), raw, hashlib.sha256
        ).hexdigest(),
    })

    async with get_db_session() as db:
        db.add(RelayDelivery(
            webhook_id=f"hook_{uuid.uuid4().hex}",
            agent_id=agent.id,
            status="pending",
            body=envelope,
            target_path=endpoint.target_path,
        ))
        await db.commit()
    await _bump_stats(endpoint.id, 202)
    return Response(
        content=json.dumps({"status": "accepted"}),
        status_code=status.HTTP_202_ACCEPTED,
        media_type="application/json",
    )
