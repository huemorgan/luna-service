"""Universal credential-gateway proxy: /proxy/{service_slug}/{path}.

Tenant Luna machines call this thinking it's the real provider. Requests
carrying an lsv1- tenant token get the real pool key injected (managed,
billable). Anything else is BYOK passthrough: forwarded unchanged, never
billed, never logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse

from cloud.billing.rating import AttemptFacts
from cloud.db import session as db_session
from cloud.db.models import GatewayKey, GatewayService
from cloud.gateway import adapters as usage_adapters
from cloud.gateway import enforcement
from cloud.gateway import keys as key_pool
from cloud.gateway import policy
from cloud.gateway import tokens as token_svc
from cloud.gateway.crypto import decrypt_key
from cloud.gateway.metering import UsageScanner, record_usage
from cloud.gateway.registry import AuthStyle, get_service_cached, parse_auth_style
from cloud.provisioning.model_catalog import cached_system_catalog, catalog_has
from cloud.relay import capture as composio_capture

log = logging.getLogger(__name__)

router = APIRouter(tags=["gateway"])

_client: httpx.AsyncClient | None = None

# Plan 018: managed requests to these services are gated on the model catalog.
# service_slug == provider for both. Other services (e.g. composio) are not gated.
_MODEL_GATED_PROVIDERS = {"anthropic", "openai", "xai", "moonshot"}

# Status codes that trigger a fallback to the next pool key (managed flow only).
_FALLBACK_STATUSES = (401, 403, 429)
# Hop-by-hop / proxy-internal headers never forwarded upstream.
_DROP_REQUEST_HEADERS = ("host", "cookie", "content-length", "accept-encoding", "connection")
_DROP_RESPONSE_HEADERS = ("transfer-encoding", "content-length", "content-encoding", "connection")


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        from cloud.observability import httpx_timing_hooks
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(300, connect=15),
            event_hooks=httpx_timing_hooks("gateway"),
        )
    return _client


async def _mark_key_used_bg(key_id: uuid.UUID) -> None:
    """Post-response bookkeeping — runs as a task so streaming starts immediately."""
    try:
        async with db_session.get_session() as db:
            await key_pool.mark_key_used(db, key_id)
            await db.commit()
    except Exception:  # noqa: BLE001 — bookkeeping must never break the response
        log.exception("mark_key_used failed for key %s", key_id)


def _requested_model(body: bytes) -> str | None:
    """Pull the `model` field from a JSON request body. None if not present /
    not JSON — non-LLM paths (e.g. /v1/models GET) are not gated."""
    if not body:
        return None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict):
        model = data.get("model")
        if isinstance(model, str) and model:
            return model
    return None


def _strip_tenant_body_api_key(body: bytes, credential: str) -> bytes:
    """Drop a JSON-body ``api_key`` that is the managed tenant token.

    Tavily (and similar body-auth APIs) prefer ``api_key`` in the JSON body over
    ``Authorization``. Older plugin-web-access clients put the ``lsv1-`` device
    token in the body while the proxy injects the real pool key as Bearer —
    upstream then 401s on the body token. Strip that body field so the injected
    header wins. BYOK bodies (real provider keys) are left untouched.
    """
    if not body or not token_svc.is_tenant_token(credential):
        return body
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body
    if not isinstance(data, dict):
        return body
    body_key = data.get("api_key")
    if not isinstance(body_key, str):
        return body
    if body_key == credential or token_svc.is_tenant_token(body_key):
        data = {k: v for k, v in data.items() if k != "api_key"}
        return json.dumps(data, separators=(",", ":")).encode()
    return body


def _upstream_headers(request: Request, auth: AuthStyle, credential: str) -> dict[str, str]:
    # X-Luna-* headers are internal correlation metadata (039/004) — they
    # must never reach a provider, managed or BYOK.
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _DROP_REQUEST_HEADERS
        and k.lower() != auth.header.lower()
        and not k.lower().startswith("x-luna-")
    }
    if not auth.is_query:
        headers[auth.header] = auth.render(credential)
    return headers


def _upstream_url(request: Request, service: GatewayService, path: str,
                  auth: AuthStyle, credential: str) -> str:
    # Clients built on provider SDKs often send the API version prefix in the
    # path (e.g. /proxy/openai/v1/...) even though the service's upstream_url
    # already ends with it — dedupe so both spellings reach the same upstream.
    base = service.upstream_url.rstrip("/")
    first, _, rest = path.partition("/")
    if rest and base.endswith(f"/{first}"):
        path = rest
    url = f"{base}/{path}"
    if auth.is_query:
        # Key-in-query APIs (plan 026): swap the inbound token param for the real
        # key; preserve every other query param.
        from urllib.parse import urlencode
        params = [(k, v) for k, v in request.query_params.multi_items() if k != auth.header]
        params.append((auth.header, credential))
        return f"{url}?{urlencode(params)}"
    if request.url.query:
        url += f"?{request.url.query}"
    return url


async def _send_upstream(
    request: Request,
    service: GatewayService,
    path: str,
    auth: AuthStyle,
    credential: str,
    body: bytes,
) -> httpx.Response:
    req = _get_client().build_request(
        method=request.method,
        url=_upstream_url(request, service, path, auth, credential),
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
    billing: enforcement.BillingContext | None = None,
    attempts: list[AttemptFacts] | None = None,
    attempt_number: int = 1,
) -> StreamingResponse:
    content_type = resp.headers.get("content-type", "")
    scanner = UsageScanner(content_type)
    # 039/004: billing-grade usage collection for metered routes. The legacy
    # UsageScanner dual-write above stays as telemetry only.
    collector = None
    if billing is not None and billing.active:
        collector = usage_adapters.make_collector(billing.adapter, content_type)
    # Plan 018: a failed upstream call (4xx/5xx) is recorded for visibility but is
    # never billable — kills the phantom input-only rows.
    billable = billable and resp.status_code < 400
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
                if collector is not None:
                    collector.feed(chunk)
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
            if collector is not None:
                # Financial settlement: persist attempt facts + rated charge
                # and enqueue the durable settle/release job. Shielded so a
                # client disconnect cannot cancel the write mid-flight; if the
                # process dies first, the stale-hold reaper reconciles.
                facts = collector.finish(resp.status_code, resp.headers)
                attempts.append(AttemptFacts(
                    provider=billing.provider,
                    model=facts.model or billing.canonical_model,
                    dimensions=facts.dimensions,
                    billable=resp.status_code < 400,
                    attempt_number=attempt_number,
                    cost_source="provider_usage" if facts.usage_seen else "estimated",
                    provider_request_id=facts.provider_request_id,
                    provider_response_id=facts.provider_response_id,
                ))
                try:
                    await asyncio.shield(
                        enforcement.finalize(billing, attempts, resp.status_code)
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 — reaper is the backstop
                    log.exception("billing finalize failed for %s", service_slug)
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
    body = await request.body()

    # One DB session covers the entire pre-flight (service, token, policy,
    # keys, catalog) — this used to be 2-3 sessions per request.
    async with db_session.get_session() as db:
        service = await get_service_cached(db, service_slug)
        if service is None or not service.enabled:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown service")

        # A row created without a template can have a blank upstream/auth_style;
        # fail loud with a 502 instead of crashing mid-forward.
        if not (service.upstream_url or "").strip():
            log.error("gateway service %s has no upstream_url", service_slug)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Service '{service_slug}' is misconfigured: no upstream URL",
            )
        try:
            auth = parse_auth_style(service.auth_style)
        except ValueError:
            log.error("gateway service %s has invalid auth_style %r",
                      service_slug, service.auth_style)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Service '{service_slug}' is misconfigured: invalid auth style",
            )
        if auth.is_query:
            credential = request.query_params.get(auth.header, "").strip()
        else:
            raw_header = request.headers.get(auth.header, "")
            credential = auth.extract(raw_header) if raw_header else ""
        if not credential:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credential")

        if token_svc.is_tenant_token(credential):
            agent_id = await token_svc.verify_token(db, credential)
            if agent_id is None:
                # A machine holding a revoked/unknown token means every LLM call
                # it makes is failing — this must be visible in Error Tracking.
                from cloud.observability.error_sink import record_error_event
                await record_error_event(
                    kind="gateway_auth",
                    severity="critical",
                    message=f"Invalid tenant token on gateway service '{service_slug}' "
                            "(machine token revoked or unknown — agent LLM calls are failing)",
                    route=f"/proxy/{service_slug}",
                )
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid tenant token")
            # Plan 026.1 guardrails: per-agent allow/deny + budget. Default = allow.
            denied = await policy.deny_reason(db, agent_id, service_slug)
            if denied:
                log.warning("gateway policy blocked agent=%s service=%s: %s",
                            agent_id, service_slug, denied)
                await record_usage(
                    agent_id=agent_id, service_slug=service_slug, billable=False,
                    key_id=None, status_code=403, input_tokens=0, output_tokens=0,
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"error": {"type": "forbidden", "message": denied}},
                )
            pool = await key_pool.resolve_keys(db, service_slug, agent_id)
            if not pool:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"No active key available for service '{service_slug}'",
                )
            # Decrypt before leaving the session; never log these.
            candidates = [(k.id, decrypt_key(k.api_key_enc)) for k in pool[:2]]

            # ── Catalog enforcement (managed flow only, Plan 018) ────────
            # Off-catalog model → 404 BEFORE spending a pool key. Aliases
            # resolve. Only LLM providers are gated; non-LLM services and
            # bodyless/GET paths skip.
            catalog = None
            if service_slug in _MODEL_GATED_PROVIDERS:
                model = _requested_model(body)
                if model is not None:
                    catalog = await cached_system_catalog(db)
                    if not catalog_has(catalog, service_slug, model):
                        log.warning(
                            "gateway off-catalog model rejected: service=%s model=%s agent=%s",
                            service_slug, model, agent_id,
                        )
                        await record_usage(
                            agent_id=agent_id,
                            service_slug=service_slug,
                            billable=False,
                            key_id=None,
                            status_code=404,
                            input_tokens=0,
                            output_tokens=0,
                        )
                        return JSONResponse(
                            status_code=status.HTTP_404_NOT_FOUND,
                            content={"error": {
                                "type": "not_found",
                                "message": (
                                    f"Model '{model}' is not in this workspace's catalog. "
                                    "Ask your admin to enable it."
                                ),
                            }},
                        )

            # ── Billing pre-flight (039/004, managed flow only) ───────────
            # Classify the route, snapshot pricing versions, and in enforce
            # mode open the ledger hold BEFORE any provider contact. BYOK
            # traffic never reaches this point.
            try:
                body_json = json.loads(body) if body else None
            except (ValueError, TypeError):
                body_json = None
            if not isinstance(body_json, dict):
                body_json = None
            billing = await enforcement.prepare(
                db,
                request=request,
                service_slug=service_slug,
                method=request.method,
                path=path,
                body=body,
                body_json=body_json,
                agent_id=agent_id,
                catalog=catalog,
            )
            if billing.block is not None:
                await record_usage(
                    agent_id=agent_id, service_slug=service_slug, billable=False,
                    key_id=None, status_code=402, input_tokens=0, output_tokens=0,
                )
                return enforcement.block_response(billing.block)
            body = billing.body or body
            # After billing may have rewritten the body, still strip a tenant
            # token mistakenly sent as JSON api_key (Tavily 401 class of bug).
            body = _strip_tenant_body_api_key(body, credential)
        else:
            agent_id = None
            candidates = None
            billing = None

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
    billing_attempts: list[AttemptFacts] = []

    def _failed_attempt(attempt_number: int) -> None:
        """Record a provider attempt that produced no usable result — its
        cost (if any usage ever surfaces) is Luna-absorbed, never charged."""
        if billing is not None and billing.active:
            billing_attempts.append(AttemptFacts(
                provider=billing.provider,
                model=billing.canonical_model,
                dimensions={},
                billable=False,
                attempt_number=attempt_number,
            ))

    for attempt, (key_id, real_key) in enumerate(candidates):
        try:
            resp = await _send_upstream(request, service, path, auth, real_key, body)
        except httpx.HTTPError as exc:
            # No provider result at all — release the hold (nothing accepted).
            if billing is not None and billing.active:
                _failed_attempt(attempt + 1)
                await enforcement.finalize(billing, billing_attempts, status_code=502)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Upstream '{service_slug}' unreachable: {type(exc).__name__}",
            )
        if resp.status_code in _FALLBACK_STATUSES and attempt + 1 < len(candidates):
            await resp.aread()
            await resp.aclose()
            _failed_attempt(attempt + 1)
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
            # Fire-and-forget: don't hold up first-byte on a bookkeeping write.
            asyncio.create_task(_mark_key_used_bg(key_id))
        return _stream_response(
            resp,
            service_slug=service_slug,
            agent_id=agent_id,
            billable=True,
            key_id=key_id,
            billing=billing,
            attempts=billing_attempts,
            attempt_number=attempt + 1,
        )

    # Unreachable in practice (loop always returns), kept for type-safety.
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "All keys failed")
