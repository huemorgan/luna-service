"""Universal credential-gateway proxy: /proxy/{service_slug}/{path}.

Tenant Luna machines call this thinking it's the real provider. Requests
carrying an lsv1- tenant token get the real pool key injected (managed,
billable). Anything else is BYOK passthrough: forwarded unchanged, never
billed, never logged.
"""

from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse

from cloud.db import session as db_session
from cloud.db.models import GatewayKey, GatewayService
from cloud.gateway import keys as key_pool
from cloud.gateway import tokens as token_svc
from cloud.gateway.crypto import decrypt_key
from cloud.gateway.metering import UsageScanner, record_usage
from cloud.gateway.registry import AuthStyle, get_service, parse_auth_style
from cloud.relay import capture as composio_capture

log = logging.getLogger(__name__)

router = APIRouter(tags=["gateway"])

_client: httpx.AsyncClient | None = None

# Status codes that trigger a fallback to the next pool key (managed flow only).
_FALLBACK_STATUSES = (401, 403, 429)
# Hop-by-hop / proxy-internal headers never forwarded upstream.
_DROP_REQUEST_HEADERS = ("host", "cookie", "content-length", "accept-encoding", "connection")
_DROP_RESPONSE_HEADERS = ("transfer-encoding", "content-length", "content-encoding", "connection")


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=15))
    return _client


def _upstream_headers(request: Request, auth: AuthStyle, credential: str) -> dict[str, str]:
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _DROP_REQUEST_HEADERS and k.lower() != auth.header.lower()
    }
    headers[auth.header] = auth.render(credential)
    return headers


async def _send_upstream(
    request: Request,
    service: GatewayService,
    path: str,
    auth: AuthStyle,
    credential: str,
    body: bytes,
) -> httpx.Response:
    url = f"{service.upstream_url.rstrip('/')}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    req = _get_client().build_request(
        method=request.method,
        url=url,
        headers=_upstream_headers(request, auth, credential),
        content=body or None,
    )
    return await _get_client().send(req, stream=True)


def _stream_response(
    resp: httpx.Response,
    *,
    service_slug: str,
    agent_id: uuid.UUID | None,
    billable: bool,
    key_id: uuid.UUID | None,
) -> StreamingResponse:
    content_type = resp.headers.get("content-type", "")
    scanner = UsageScanner(content_type)
    response_headers = {
        k: v for k, v in resp.headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS
    }
    if "text/event-stream" in content_type:
        response_headers["cache-control"] = "no-cache"
        response_headers["x-accel-buffering"] = "no"

    # Plan 015: harvest connected-account ids from Composio responses so the
    # trigger relay can route webhook events to this agent.
    capture_composio = (
        service_slug == "composio" and agent_id is not None and resp.status_code < 400
    )
    capture_buf = bytearray()

    async def stream():
        try:
            async for chunk in resp.aiter_bytes():
                scanner.feed(chunk)
                if capture_composio and len(capture_buf) <= composio_capture.MAX_CAPTURE_BYTES:
                    capture_buf.extend(chunk)
                yield chunk
        finally:
            await resp.aclose()
            try:
                await record_usage(
                    agent_id=agent_id,
                    service_slug=service_slug,
                    billable=billable,
                    key_id=key_id,
                    status_code=resp.status_code,
                    input_tokens=scanner.input_tokens,
                    output_tokens=scanner.output_tokens,
                )
            except Exception:  # noqa: BLE001 — metering must never break the response
                log.exception("usage_event write failed for %s", service_slug)
            if capture_composio:
                # Best-effort; never breaks the response (same rule as metering).
                await composio_capture.capture_from_gateway_response(
                    agent_id, content_type, bytes(capture_buf),
                )

    return StreamingResponse(
        stream(),
        status_code=resp.status_code,
        headers=response_headers,
        media_type=content_type or None,
    )


@router.api_route(
    "/proxy/{service_slug}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def gateway_proxy(request: Request, service_slug: str, path: str = ""):
    async with db_session.get_session() as db:
        service = await get_service(db, service_slug)
        if service is None or not service.enabled:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown service")

        auth = parse_auth_style(service.auth_style)
        raw_header = request.headers.get(auth.header, "")
        credential = auth.extract(raw_header) if raw_header else ""
        if not credential:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credential")

        if token_svc.is_tenant_token(credential):
            agent_id = await token_svc.verify_token(db, credential)
            if agent_id is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid tenant token")
            pool = await key_pool.resolve_keys(db, service_slug, agent_id)
            if not pool:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"No active key available for service '{service_slug}'",
                )
            # Decrypt before leaving the session; never log these.
            candidates = [(k.id, decrypt_key(k.api_key_enc)) for k in pool[:2]]
        else:
            agent_id = None
            candidates = None

    body = await request.body()

    # ── BYOK passthrough ─────────────────────────────────────────────────
    if candidates is None:
        try:
            resp = await _send_upstream(request, service, path, auth, credential, body)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Upstream '{service_slug}' unreachable: {type(exc).__name__}",
            )
        return _stream_response(
            resp,
            service_slug=service_slug,
            agent_id=None,
            billable=False,
            key_id=None,
        )

    # ── Managed flow with one fallback retry ─────────────────────────────
    for attempt, (key_id, real_key) in enumerate(candidates):
        try:
            resp = await _send_upstream(request, service, path, auth, real_key, body)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Upstream '{service_slug}' unreachable: {type(exc).__name__}",
            )
        if resp.status_code in _FALLBACK_STATUSES and attempt + 1 < len(candidates):
            await resp.aread()
            await resp.aclose()
            async with db_session.get_session() as db:
                await key_pool.mark_key_failure(db, key_id, resp.status_code)
                await db.commit()
            log.warning(
                "gateway key fallback: service=%s key=%s status=%s",
                service_slug, key_id, resp.status_code,
            )
            continue
        if resp.status_code in _FALLBACK_STATUSES:
            # Last candidate also failed — cooldown it and return the error.
            async with db_session.get_session() as db:
                await key_pool.mark_key_failure(db, key_id, resp.status_code)
                await db.commit()
        else:
            async with db_session.get_session() as db:
                await key_pool.mark_key_used(db, key_id)
                await db.commit()
        return _stream_response(
            resp,
            service_slug=service_slug,
            agent_id=agent_id,
            billable=True,
            key_id=key_id,
        )

    # Unreachable in practice (loop always returns), kept for type-safety.
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "All keys failed")
