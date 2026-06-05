"""Reverse proxy — routes /a/{agent_slug}/… to the user's Luna instance."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from cloud.auth.session import get_session
from cloud.db.models import Agent, Membership, User
from cloud.db.session import get_session as get_db_session

log = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])

_http_client: httpx.AsyncClient | None = None

# In-memory wake locks: agent_slug → asyncio.Event
# Prevents multiple simultaneous requests from all trying to wake the same machine
_wake_locks: dict[str, asyncio.Event] = {}


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
    return _http_client


async def _resolve_agent(request: Request, agent_slug: str):
    """Resolve session + agent, verifying the user has access."""
    sess = get_session(request)
    if not sess:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    async with get_db_session() as db:
        user = (await db.execute(
            select(User).where(User.id == uuid.UUID(sess["user_id"]))
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

        agent = (await db.execute(
            select(Agent).where(Agent.slug == agent_slug)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

        membership = (await db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.account_id == agent.account_id,
                Membership.status == "active",
            )
        )).scalar_one_or_none()
        if not membership:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this account")

        return user, agent


async def _try_wake_agent(agent: Agent) -> bool:
    """Attempt to start a stopped/crashed Fly machine. Returns True on success."""
    if not agent.runtime_ref or not os.environ.get("FLY_API_TOKEN"):
        return False

    slug = agent.slug

    # If another request is already waking this agent, wait for it
    if slug in _wake_locks:
        event = _wake_locks[slug]
        try:
            await asyncio.wait_for(event.wait(), timeout=30)
        except asyncio.TimeoutError:
            return False
        return event.is_set()

    # We're the first — take the lock
    event = asyncio.Event()
    _wake_locks[slug] = event

    try:
        from cloud.runtime.fly_machines import FlyMachinesRuntime
        from cloud.runtime.base import RuntimeHandle

        fly = FlyMachinesRuntime()
        handle = RuntimeHandle(
            agent.runtime_kind or "fly-machine",
            agent.runtime_ref,
            agent.internal_url or "",
        )
        await fly.start(handle)

        async with get_db_session() as db:
            a = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
            a.status = "running"
            a.error_message = None
            a.error_at = None
            await db.commit()

        log.info("Auto-woke agent %s (machine %s)", slug, agent.runtime_ref)
        event.set()
        return True
    except Exception as exc:
        log.error("Failed to auto-wake agent %s: %s", slug, exc)
        return False
    finally:
        _wake_locks.pop(slug, None)


async def _proxy_request(
    request: Request, user: User, agent: Agent, agent_slug: str, path: str,
) -> Response:
    """Build and send the proxied request. Returns the response."""
    proxy_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")

    target_url = f"{agent.internal_url}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("cookie", None)
    headers.pop("accept-encoding", None)
    headers["x-luna-user"] = user.email
    headers["x-luna-proxy-secret"] = proxy_secret

    if agent.runtime_ref:
        headers["fly-force-instance-id"] = agent.runtime_ref

    client = _get_http_client()
    body = await request.body()

    req = client.build_request(
        method=request.method,
        url=target_url,
        headers=headers,
        content=body if body else None,
    )

    log.info("Proxying %s %s → %s", request.method, request.url.path, target_url)
    resp = await client.send(req, stream=True)

    content_type = resp.headers.get("content-type", "")
    is_html = "text/html" in content_type
    is_sse = "text/event-stream" in content_type

    response_headers = dict(resp.headers)
    response_headers.pop("transfer-encoding", None)
    response_headers.pop("content-length", None)
    response_headers.pop("content-encoding", None)

    if is_html:
        html_bytes = await resp.aread()
        await resp.aclose()
        html = html_bytes.decode("utf-8", errors="replace")
        prefix = f"/a/{agent_slug}"
        html = _rewrite_html_paths(html, prefix)
        response_headers["cache-control"] = "no-cache, no-store, must-revalidate"
        return Response(
            content=html,
            status_code=resp.status_code,
            headers=response_headers,
            media_type="text/html; charset=utf-8",
        )

    if is_sse:
        response_headers["cache-control"] = "no-cache"
        response_headers["x-accel-buffering"] = "no"

    async def stream():
        async for chunk in resp.aiter_bytes():
            yield chunk
        await resp.aclose()

    return StreamingResponse(
        stream(),
        status_code=resp.status_code,
        headers=response_headers,
        media_type=content_type,
    )


@router.api_route(
    "/a/{agent_slug}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
@router.api_route(
    "/a/{agent_slug}/",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
@router.api_route(
    "/a/{agent_slug}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy_to_luna(request: Request, agent_slug: str, path: str = ""):
    user, agent = await _resolve_agent(request, agent_slug)

    if not agent.runtime_ref:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent has no runtime")

    # If DB says stopped, try to wake before proxying
    if agent.status in ("stopped", "error"):
        woke = await _try_wake_agent(agent)
        if not woke:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Luna could not be started")

    # Try proxying the request
    try:
        return await _proxy_request(request, user, agent, agent_slug, path)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
        # Machine might have died while DB still says "running" — try to wake it
        log.warning("Proxy failed for %s, attempting auto-wake: %s", agent_slug, exc)

        woke = await _try_wake_agent(agent)
        if not woke:
            # Update DB to reflect the machine is down
            async with get_db_session() as db:
                a = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
                a.status = "error"
                a.error_message = f"Machine unreachable: {type(exc).__name__}"
                a.error_at = datetime.now(timezone.utc)
                await db.commit()
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Luna instance is unreachable and could not be restarted",
            )

        # Retry once after wake
        try:
            return await _proxy_request(request, user, agent, agent_slug, path)
        except Exception as retry_exc:
            log.error("Proxy retry failed after wake for %s: %s", agent_slug, retry_exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Luna restarted but still unreachable: {type(retry_exc).__name__}",
            )
    except Exception as exc:
        log.error("Proxy connection failed: %s: %s", agent_slug, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Cannot reach Luna instance: {type(exc).__name__}",
        )


def _rewrite_html_paths(html: str, prefix: str) -> str:
    """Rewrite absolute asset paths in Luna's HTML to include the slug prefix.

    Also injects a fetch-interceptor script so API calls from the React app
    are automatically prefixed with the slug path.
    """
    html = re.sub(r'(src|href)="/', rf'\1="{prefix}/', html)
    interceptor = (
        f'<script>window.__LUNA_BASE="{prefix}";'
        "(function(){"
        "var B=window.__LUNA_BASE;"
        "var _f=window.fetch;window.fetch=function(u,o){"
        "if(typeof u==='string'&&u.startsWith('/')&&!u.startsWith(B))u=B+u;"
        "return _f.call(this,u,o);};"
        "var _xhr=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){"
        "if(typeof u==='string'&&u.startsWith('/')&&!u.startsWith(B))u=B+u;"
        "return _xhr.apply(this,[m,u].concat([].slice.call(arguments,2)));};"
        "var dP=Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype,'src');"
        "Object.defineProperty(HTMLIFrameElement.prototype,'src',{"
        "set:function(v){if(typeof v==='string'&&v.startsWith('/')&&!v.startsWith(B))v=B+v;dP.set.call(this,v);},"
        "get:function(){return dP.get.call(this);}});"
        "})();</script>"
    )
    html = html.replace("</head>", interceptor + "</head>")
    return html
