"""Reverse proxy — routes /{slug}/… to the user's Luna instance."""

from __future__ import annotations

import os
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from cloud.auth.session import get_session
from cloud.db.models import Account, Agent, Membership, User
from cloud.db.session import get_session as get_db_session

router = APIRouter(tags=["proxy"])

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
    return _http_client


async def _resolve_context(request: Request, account_slug: str):
    """Resolve session + account + agent, raising appropriate errors."""
    sess = get_session(request)
    if not sess:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    async with get_db_session() as db:
        user = (await db.execute(
            select(User).where(User.id == uuid.UUID(sess["user_id"]))
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

        account = (await db.execute(
            select(Account).where(Account.slug == account_slug)
        )).scalar_one_or_none()
        if not account:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")

        membership = (await db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.account_id == account.id,
                Membership.status == "active",
            )
        )).scalar_one_or_none()
        if not membership:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this account")

        agent = (await db.execute(
            select(Agent).where(Agent.account_id == account.id)
        )).scalar_one_or_none()

        return user, account, agent


@router.get("/api/agents/me/status")
async def agent_status(request: Request):
    """Returns the current user's Luna agent status for polling."""
    sess = get_session(request)
    if not sess:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    async with get_db_session() as db:
        account = (await db.execute(
            select(Account).where(Account.id == uuid.UUID(sess["account_id"]))
        )).scalar_one_or_none()
        if not account:
            raise HTTPException(status.HTTP_404_NOT_FOUND)

        agent = (await db.execute(
            select(Agent).where(Agent.account_id == account.id)
        )).scalar_one_or_none()

    return {
        "slug": account.slug,
        "status": agent.status if agent else "pending",
        "internal_url": agent.internal_url if agent else None,
    }


_RESERVED = {"api", "auth", "healthz", "assets", "favicon.svg", "icons.svg", "dashboard"}


@router.api_route(
    "/{account_slug}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy_to_luna(request: Request, account_slug: str, path: str):
    if account_slug in _RESERVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    user, account, agent = await _resolve_context(request, account_slug)

    if not agent or agent.status != "running":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Luna is not ready yet")

    proxy_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")

    target_url = f"{agent.internal_url}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("cookie", None)
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

    resp = await client.send(req, stream=True)

    is_sse = "text/event-stream" in resp.headers.get("content-type", "")

    async def stream():
        async for chunk in resp.aiter_bytes():
            yield chunk
        await resp.aclose()

    response_headers = dict(resp.headers)
    response_headers.pop("transfer-encoding", None)

    if is_sse:
        response_headers["cache-control"] = "no-cache"
        response_headers["x-accel-buffering"] = "no"

    return StreamingResponse(
        stream(),
        status_code=resp.status_code,
        headers=response_headers,
        media_type=resp.headers.get("content-type"),
    )
