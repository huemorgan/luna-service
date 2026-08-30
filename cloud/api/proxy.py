"""Reverse proxy — routes /a/{agent_slug}/… to the user's Luna instance."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import json

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from cloud.auth.session import get_session
from cloud.db.models import Agent, User
from cloud.db.session import get_session as get_db_session
from cloud.observability.error_sink import record_error_event

log = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])

_http_client: httpx.AsyncClient | None = None

# How long piggy-backing requests wait for an in-flight wake before giving up.
WAKE_WAIT_TIMEOUT = 10


class _WakeAttempt:
    """One in-flight wake: an event waiters block on + the outcome."""

    __slots__ = ("event", "success")

    def __init__(self) -> None:
        self.event = asyncio.Event()
        self.success = False


# In-memory wake locks: agent_slug → attempt.
# Prevents multiple simultaneous requests from all trying to wake the same machine
_wake_locks: dict[str, _WakeAttempt] = {}


def _stream_idle_read_seconds() -> float:
    """Per-chunk idle allowance for proxied SSE streams (045/phase06).

    Long agent tool runs can emit nothing for minutes; the default 120 s read
    timeout killed those turns as ReadTimeout storms in the Render logs."""
    try:
        return float(os.environ.get("PROXY_STREAM_IDLE_READ", "300"))
    except ValueError:
        return 300.0


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        from cloud.observability import httpx_timing_hooks
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120, connect=10),
            event_hooks=httpx_timing_hooks("agent-proxy"),
        )
    return _http_client


async def _resolve_agent(request: Request, agent_slug: str):
    """Resolve session + agent, verifying the user has access.

    User + membership come from the auth TTL cache (plan 037-SPEED101); the
    agent row is always fresh because its status drives the wake logic.
    """
    from cloud.auth.deps import check_membership_cached, load_user_cached

    sess = get_session(request)
    if not sess or "user_id" not in sess:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    user = await load_user_cached(sess["user_id"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.slug == agent_slug)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

    if not await check_membership_cached(sess["user_id"], str(agent.account_id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this account")

    return user, agent


async def _mark_agent_error(agent_id, message: str) -> None:
    async with get_db_session() as db:
        a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
        a.status = "error"
        a.error_message = message
        a.error_at = datetime.now(timezone.utc)
        await db.commit()


async def _try_wake_agent(agent: Agent) -> bool:
    """Attempt to start a stopped/crashed Fly machine. Returns True on success.

    Fail-fast: if the machine no longer exists, marks the agent error and
    returns immediately instead of letting every caller burn a full timeout.
    """
    if not agent.runtime_ref or not os.environ.get("FLY_API_TOKEN"):
        return False

    # 039/005: a payment_due Luna must not wake through traffic — recovery is
    # the explicit start endpoint (which re-charges). Effective enforce mode
    # only (global or the account's 039/010 override; hosting_blocked resolves it).
    from cloud.billing import hosting as billing_hosting
    async with get_db_session() as db:
        if await billing_hosting.hosting_blocked(db, agent.id):
            log.info("Wake %s blocked: hosting payment due", agent.slug)
            return False

    slug = agent.slug

    # If another request is already waking this agent, wait for it
    attempt = _wake_locks.get(slug)
    if attempt is not None:
        try:
            await asyncio.wait_for(attempt.event.wait(), timeout=WAKE_WAIT_TIMEOUT)
        except asyncio.TimeoutError:
            return False
        return attempt.success

    # We're the first — take the lock
    attempt = _WakeAttempt()
    _wake_locks[slug] = attempt

    try:
        from cloud.runtime.fly_machines import FlyMachinesRuntime
        from cloud.runtime.base import RuntimeHandle

        fly = FlyMachinesRuntime()

        # Machine gone entirely? Mark error and bail — no wait, no retries.
        machine = await fly.describe(agent.runtime_ref)
        if machine is None:
            log.warning("Wake %s: machine %s no longer exists", slug, agent.runtime_ref)
            await _mark_agent_error(agent.id, "Machine no longer exists")
            await record_error_event(
                kind="agent_wake_failed", severity="critical",
                message="Machine no longer exists",
                route=f"/a/{slug}",
                context={"runtime_ref": agent.runtime_ref},
                agent_id=agent.id, account_id=agent.account_id,
            )
            return False

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
        attempt.success = True
        return True
    except Exception as exc:
        log.error("Failed to auto-wake agent %s: %s", slug, exc)
        await record_error_event(
            kind="agent_wake_failed", severity="error",
            message=f"Failed to auto-wake agent: {type(exc).__name__}: {exc}",
            route=f"/a/{slug}",
            context={"runtime_ref": agent.runtime_ref},
            agent_id=agent.id, account_id=agent.account_id,
        )
        return False
    finally:
        # Always release waiters — before this fix a failed wake left them
        # blocked for the full timeout.
        attempt.event.set()
        _wake_locks.pop(slug, None)


# Keep strong refs to fire-and-forget wake tasks so they aren't GC'd mid-flight.
_background_wakes: set[asyncio.Task] = set()


def _spawn_wake(agent: Agent) -> None:
    """Fire-and-forget wake. Deduped by the wake lock in _try_wake_agent."""
    task = asyncio.create_task(_try_wake_agent(agent))
    _background_wakes.add(task)
    task.add_done_callback(_background_wakes.discard)


def _is_page_navigation(request: Request) -> bool:
    """A browser navigating to a page (as opposed to fetch/XHR/asset/SSE)."""
    return request.method == "GET" and "text/html" in request.headers.get("accept", "")


class _UpstreamGatewayError(Exception):
    """Upstream answered a page navigation with 502/503/504 — usually Fly's
    edge speaking for a stopped/booting machine instead of refusing the
    connection (plan 067). Only ever raised for page navigations."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


_HOLDING_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Waking Luna…</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#0f0f14;color:#e4e4ef;font-family:'Inter',system-ui,-apple-system,sans-serif;
       -webkit-font-smoothing:antialiased}
  .wrap{text-align:center;padding:2rem;max-width:26rem}
  .spinner{width:44px;height:44px;margin:0 auto 1.5rem;border-radius:50%;
           border:3px solid #2a2a3a;border-top-color:#c9b8ff;animation:spin 0.9s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  h1{font-size:1.15rem;font-weight:600;margin:0 0 .5rem}
  p{font-size:.85rem;color:#8888a0;margin:0;line-height:1.5}
  #slow{display:none;margin-top:1.25rem;font-size:.8rem}
  a{color:#c9b8ff}
</style>
</head>
<body>
<div class="wrap">
  <div class="spinner"></div>
  <h1 id="hd">Starting Luna&rsquo;s machine</h1>
  <p id="msg">This window will refresh when Luna is ready.</p>
  <p id="slow">This is taking longer than usual. You can keep waiting, or check the
     <a href="/dashboard">dashboard</a> for its status.</p>
</div>
<script>
(function(){
  var READY_URL=__READY_URL__;
  var started=Date.now();
  function fail(detail){
    document.querySelector('.spinner').style.display='none';
    document.getElementById('hd').textContent="Luna couldn't start";
    var m=document.getElementById('msg');
    m.textContent=detail?detail+' ':'';
    var a=document.createElement('a');
    a.href='/dashboard';a.textContent='Open the dashboard';
    m.appendChild(a);
    document.getElementById('slow').style.display='none';
  }
  function poll(){
    fetch(READY_URL,{cache:'no-store'})
      .then(function(r){return r.ok?r.json():null;})
      .then(function(d){
        if(d&&d.ready){location.reload();return;}
        if(d&&d.state==='failed'){fail(d.detail);return;}
        next();
      })
      .catch(next);
  }
  function next(){
    if(Date.now()-started>90000)document.getElementById('slow').style.display='block';
    setTimeout(poll,3000);
  }
  setTimeout(poll,2000);
})();
</script>
</body>
</html>"""


def _holding_page(agent_slug: str) -> Response:
    html = _HOLDING_PAGE.replace(
        "__READY_URL__", json.dumps(f"/a/{agent_slug}/__luna_ready")
    )
    return Response(
        content=html,
        status_code=200,
        media_type="text/html; charset=utf-8",
        headers={"cache-control": "no-cache, no-store, must-revalidate"},
    )


async def _proxy_request(
    request: Request, user: User | None, agent: Agent, agent_slug: str, path: str,
) -> Response:
    """Build and send the proxied request. Returns the response."""
    from cloud.runtime.proxy_secret import derive_proxy_secret

    root_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")
    proxy_secret = derive_proxy_secret(root_secret, str(agent.id))

    target_url = f"{agent.internal_url}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("cookie", None)
    headers.pop("accept-encoding", None)
    if user is not None:
        headers["x-luna-user"] = user.email
    headers["x-luna-proxy-secret"] = proxy_secret
    # Public base for this agent, so plugins can emit public URLs (e.g. MacRunner's
    # pairing ws://…) instead of their unreachable internal address.
    _pub_host = request.headers.get("x-forwarded-host") or request.url.hostname
    _pub_scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    if _pub_host:
        headers["x-luna-public-base"] = f"{_pub_scheme}://{_pub_host}/a/{agent_slug}"

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

    # 045/phase06 (= 044 Bug 6): SSE turns can sit idle well past the client's
    # default 120 s read timeout (long tool runs emit no bytes), and each one
    # died as an httpcore.ReadTimeout raised straight through the ASGI stack
    # (the Render log storm). httpx's read timeout is already per-chunk idle,
    # so give streaming requests a longer idle allowance; genuinely stalled
    # upstreams are closed cleanly by the generator below instead of raising.
    if "text/event-stream" in request.headers.get("accept", ""):
        req.extensions["timeout"] = httpx.Timeout(
            120, connect=10, read=_stream_idle_read_seconds(),
        ).as_dict()

    log.info("Proxying %s %s → %s", request.method, request.url.path, target_url)
    resp = await client.send(req, stream=True)

    # Plan 067: Fly's edge answers for a stopped/booting machine with its own
    # 502/503/504 instead of refusing the connection. A browser navigation
    # must get the holding page, never a raw gateway error (Cloudflare
    # replaces origin 502/504 with its branded page).
    if resp.status_code in (502, 503, 504) and _is_page_navigation(request):
        await resp.aclose()
        raise _UpstreamGatewayError(resp.status_code)

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
        # 045/phase06: a stalled upstream or a client abort must end the
        # stream cleanly — no exception through the ASGI stack, no error-level
        # log, and the upstream response always closed.
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        except httpx.ReadTimeout:
            log.warning("Proxy stream idle timeout: %s", target_url)
            await record_error_event(
                kind="proxy_read_timeout", severity="warning",
                message="Proxy stream idle timeout",
                route=f"/a/{agent_slug}/{path}",
                context={"target": target_url, "method": request.method},
                agent_id=agent.id, account_id=agent.account_id,
            )
        except (httpx.ReadError, httpx.RemoteProtocolError) as exc:
            log.warning("Proxy stream broke (%s): %s", type(exc).__name__, target_url)
            await record_error_event(
                kind="proxy_502", severity="warning",
                message=f"Proxy stream broke ({type(exc).__name__})",
                route=f"/a/{agent_slug}/{path}",
                context={"target": target_url, "method": request.method},
                agent_id=agent.id, account_id=agent.account_id,
            )
        except asyncio.CancelledError:
            # Client went away mid-stream (tab closed / navigation).
            raise
        finally:
            await resp.aclose()

    return StreamingResponse(
        stream(),
        status_code=resp.status_code,
        headers=response_headers,
        media_type=content_type,
    )


async def _wake_is_hopeless(agent: Agent) -> str | None:
    """A reason string when no amount of polling will bring this Luna up —
    the holding page stops spinning and shows it (plan 067)."""
    if agent.status == "error" and "no longer exists" in (agent.error_message or ""):
        return "Luna's machine no longer exists — recreate it from the dashboard."
    from cloud.billing import hosting as billing_hosting
    async with get_db_session() as db:
        if await billing_hosting.hosting_blocked(db, agent.id):
            return "Hosting is paused until billing is settled."
    return None


@router.get("/a/{agent_slug}/__luna_ready", include_in_schema=False)
async def luna_ready(request: Request, agent_slug: str):
    """Readiness probe for the holding page. Checks the machine's /api/health
    directly; when it's down, (re)triggers a wake in the background so polling
    alone is enough to bring the machine up. Always 200; `state: "failed"`
    tells the page to stop polling and show the reason (plan 067)."""
    _, agent = await _resolve_agent(request, agent_slug)

    detail = await _wake_is_hopeless(agent)
    if detail:
        return {"ready": False, "state": "failed", "detail": detail}

    if not agent.runtime_ref or not agent.internal_url:
        return {
            "ready": False, "state": "failed",
            "detail": "This Luna has no machine to start.",
        }

    headers = {"fly-force-instance-id": agent.runtime_ref}
    try:
        client = _get_http_client()
        resp = await client.get(
            f"{agent.internal_url.rstrip('/')}/api/health",
            headers=headers,
            timeout=httpx.Timeout(3, connect=2),
        )
        if resp.status_code == 200:
            return {"ready": True}
    except Exception:  # noqa: BLE001 — any failure just means "not ready yet"
        pass

    _spawn_wake(agent)
    return {"ready": False, "state": "starting"}


# --- Token-gated HTTP pass-through (plan 077; HTTP twin of plan 062's WS) ---

# The playbook delegation progress card is embedded in chat as an opaque-origin
# srcdoc iframe (sandbox="allow-scripts…"): it can send neither the session
# cookie nor a bearer header. Its status poll is capability-scoped instead —
# the tenant route verifies a random per-delegation token baked into that one
# card's HTML (compare_digest, one 404 for unknown id AND bad token, read-only,
# ACAO: *). The proxy forwards it by slug and lets the tenant do the auth,
# mirroring _TOKEN_GATED_WS_SUFFIXES below (plan 062).
_TOKEN_GATED_GET_PATHS = re.compile(
    r"^api/p/plugin-playbooks/delegations/[0-9a-fA-F-]{1,64}/card$"
)


async def _proxy_token_gated_get(
    request: Request, agent_slug: str, path: str,
) -> Response:
    """Forward a token-gated GET with no session. Auth model: plan 077.

    Never wakes a machine: a stopped machine cannot be running a delegation,
    and an unauthenticated poll must not be able to keep a tenant awake.
    """
    agent = await _resolve_agent_by_slug(agent_slug)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    if not agent.runtime_ref or agent.status in ("stopped", "error"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent is not running")
    try:
        return await _proxy_request(request, None, agent, agent_slug, path)
    except httpx.TransportError as exc:
        log.warning("Token-gated proxy failed for %s: %s", agent_slug, type(exc).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Cannot reach Luna instance")


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
    if request.method == "GET" and _TOKEN_GATED_GET_PATHS.match(path.rstrip("/")):
        # Sessionless capability-token path — the tenant does the auth.
        return await _proxy_token_gated_get(request, agent_slug, path)

    user, agent = await _resolve_agent(request, agent_slug)

    if not agent.runtime_ref:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent has no runtime")

    # Browser page loads get a self-refreshing holding page instead of an
    # error while the machine boots; API/asset/SSE requests keep the old
    # block-and-retry behavior.
    wants_page = _is_page_navigation(request)

    # If DB says stopped, try to wake before proxying
    if agent.status in ("stopped", "error"):
        if wants_page:
            _spawn_wake(agent)
            return _holding_page(agent_slug)
        woke = await _try_wake_agent(agent)
        if not woke:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Luna could not be started")

    # Try proxying the request
    try:
        return await _proxy_request(request, user, agent, agent_slug, path)
    except _UpstreamGatewayError as exc:
        # Only raised for page navigations: the machine is evidently not
        # serving even though the DB says "running" — wake it and hold.
        log.warning(
            "Upstream %s on page load for %s — serving holding page",
            exc.status_code, agent_slug,
        )
        await record_error_event(
            kind="proxy_502", severity="warning",
            message=f"Upstream {exc.status_code} on page load — served holding page",
            route=f"/a/{agent_slug}/{path}",
            context={"method": request.method, "status_code": exc.status_code},
            agent_id=agent.id, account_id=agent.account_id,
        )
        _spawn_wake(agent)
        return _holding_page(agent_slug)
    except httpx.TransportError as exc:
        # Machine might have died while DB still says "running" — try to wake it
        log.warning("Proxy failed for %s, attempting auto-wake: %s", agent_slug, exc)
        if wants_page:
            _spawn_wake(agent)
            return _holding_page(agent_slug)

        woke = await _try_wake_agent(agent)
        if not woke:
            # Update DB to reflect the machine is down
            async with get_db_session() as db:
                a = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
                a.status = "error"
                a.error_message = f"Machine unreachable: {type(exc).__name__}"
                a.error_at = datetime.now(timezone.utc)
                await db.commit()
            await record_error_event(
                kind="proxy_502", severity="error",
                message="Luna instance is unreachable and could not be restarted",
                route=f"/a/{agent_slug}/{path}",
                context={"method": request.method, "error": type(exc).__name__},
                agent_id=agent.id, account_id=agent.account_id,
            )
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Luna instance is unreachable and could not be restarted",
            )

        # Retry once after wake
        try:
            return await _proxy_request(request, user, agent, agent_slug, path)
        except Exception as retry_exc:
            log.error("Proxy retry failed after wake for %s: %s", agent_slug, retry_exc)
            await record_error_event(
                kind="proxy_502", severity="error",
                message=f"Luna restarted but still unreachable: {type(retry_exc).__name__}",
                route=f"/a/{agent_slug}/{path}",
                context={"method": request.method},
                agent_id=agent.id, account_id=agent.account_id,
            )
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Luna restarted but still unreachable: {type(retry_exc).__name__}",
            )
    except Exception as exc:
        log.error("Proxy connection failed: %s: %s", agent_slug, exc)
        await record_error_event(
            kind="proxy_502", severity="error",
            message=f"Cannot reach Luna instance: {type(exc).__name__}: {exc}",
            route=f"/a/{agent_slug}/{path}",
            context={"method": request.method},
            agent_id=agent.id, account_id=agent.account_id,
        )
        # Plan 067: whatever went wrong, a page navigation never sees a 5xx.
        if wants_page:
            _spawn_wake(agent)
            return _holding_page(agent_slug)
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
        # Intercept fetch
        "var _f=window.fetch;window.fetch=function(u,o){"
        "if(typeof u==='string'&&u.startsWith('/')&&!u.startsWith(B))u=B+u;"
        "return _f.call(this,u,o);};"
        # Intercept XMLHttpRequest
        "var _xhr=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){"
        "if(typeof u==='string'&&u.startsWith('/')&&!u.startsWith(B))u=B+u;"
        "return _xhr.apply(this,[m,u].concat([].slice.call(arguments,2)));};"
        # Intercept iframe src via property descriptor + setAttribute + MutationObserver
        "function fixSrc(el){"
        "var s=el.getAttribute('src');"
        "if(s&&s.startsWith('/')&&!s.startsWith(B))el.setAttribute('src',B+s);"
        "}"
        "var _sa=HTMLIFrameElement.prototype.setAttribute;"
        "HTMLIFrameElement.prototype.setAttribute=function(n,v){"
        "if(n==='src'&&typeof v==='string'&&v.startsWith('/')&&!v.startsWith(B))v=B+v;"
        "return _sa.call(this,n,v);};"
        "var dP=Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype,'src');"
        "if(dP&&dP.set){Object.defineProperty(HTMLIFrameElement.prototype,'src',{"
        "set:function(v){if(typeof v==='string'&&v.startsWith('/')&&!v.startsWith(B))v=B+v;dP.set.call(this,v);},"
        "get:function(){return dP.get.call(this);}});}"
        "new MutationObserver(function(ms){ms.forEach(function(m){"
        "m.addedNodes.forEach(function(n){"
        "if(n.tagName==='IFRAME')fixSrc(n);"
        "if(n.querySelectorAll){n.querySelectorAll('iframe').forEach(fixSrc);}"
        "});});}).observe(document.documentElement,{childList:true,subtree:true});"
        # Intercept EventSource for SSE connections (brain widget)
        "var _ES=window.EventSource;"
        "window.EventSource=function(u,o){"
        "if(typeof u==='string'&&u.startsWith('/')&&!u.startsWith(B))u=B+u;"
        "return new _ES(u,o);};"
        "window.EventSource.prototype=_ES.prototype;"
        "window.EventSource.CONNECTING=_ES.CONNECTING;"
        "window.EventSource.OPEN=_ES.OPEN;"
        "window.EventSource.CLOSED=_ES.CLOSED;"
        "})();</script>"
    )
    # plan 051/007: browser-side error reporter, served by plugin-feedback on
    # the agent. Best-effort — 404s silently when the plugin is absent or old.
    reporter = (
        f'<script src="{prefix}/api/p/plugin-feedback/reporter.js" defer>'
        "</script>"
    )
    html = html.replace("</head>", interceptor + reporter + "</head>")
    return html


# --- WebSocket reverse proxy (plan 062) -----------------------------------

# MacRunner's pairing socket is gated by the tenant plugin's token (the native
# app has no browser session), so this path is forwarded by slug and the tenant
# does the auth. Every other WS path requires the owner's session.
_TOKEN_GATED_WS_SUFFIXES = ("api/p/luna-macrunner/ws",)


async def _resolve_agent_by_slug(agent_slug: str):
    async with get_db_session() as db:
        return (
            await db.execute(select(Agent).where(Agent.slug == agent_slug))
        ).scalar_one_or_none()


@router.websocket("/a/{agent_slug}/{path:path}")
async def proxy_websocket(websocket: WebSocket, agent_slug: str, path: str):
    """Reverse-proxy a WebSocket to the tenant's Luna. Auth model: see plan 062."""
    token_gated = path.rstrip("/").endswith(_TOKEN_GATED_WS_SUFFIXES)
    user_email: str | None = None

    if token_gated:
        # Forwarded by slug; the tenant plugin verifies the pairing token.
        agent = await _resolve_agent_by_slug(agent_slug)
        if agent is None:
            await websocket.close(code=4404)
            return
    else:
        # Browser client: require the owner's session + membership.
        sess = get_session(websocket)  # WebSocket exposes .cookies, like Request
        if not sess or "user_id" not in sess:
            await websocket.close(code=4401)
            return
        from cloud.auth.deps import check_membership_cached, load_user_cached

        user = await load_user_cached(sess["user_id"])
        agent = await _resolve_agent_by_slug(agent_slug)
        if (
            not user
            or agent is None
            or not await check_membership_cached(sess["user_id"], str(agent.account_id))
        ):
            await websocket.close(code=4403)
            return
        user_email = user.email

    if not agent.internal_url:
        await websocket.close(code=1011)
        return

    # Wake a suspended machine before dialing.
    if agent.status in ("stopped", "error"):
        await _try_wake_agent(agent)
        agent = await _resolve_agent_by_slug(agent_slug) or agent

    from cloud.runtime.proxy_secret import derive_proxy_secret

    root_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")
    proxy_secret = derive_proxy_secret(root_secret, str(agent.id))

    ws_base = (
        agent.internal_url.replace("https://", "wss://")
        .replace("http://", "ws://")
        .rstrip("/")
    )
    target = f"{ws_base}/{path}"
    if websocket.url.query:
        target += f"?{websocket.url.query}"

    headers = [("x-luna-proxy-secret", proxy_secret)]
    if user_email:
        headers.append(("x-luna-user", user_email))
    if agent.runtime_ref:
        headers.append(("fly-force-instance-id", agent.runtime_ref))

    await websocket.accept()

    try:
        import websockets  # local import: only this path needs it
    except Exception:  # noqa: BLE001
        log.error("websockets library not installed - cannot proxy WS")
        await websocket.close(code=1011)
        return

    try:
        # websockets>=12 uses additional_headers; older uses extra_headers.
        try:
            upstream_cm = websockets.connect(
                target, additional_headers=headers, open_timeout=15, max_size=None
            )
        except TypeError:
            upstream_cm = websockets.connect(
                target, extra_headers=headers, open_timeout=15, max_size=None
            )
        async with upstream_cm as upstream:
            log.info("WS proxy %s -> %s", agent_slug, target)
            await _ws_pump(websocket, upstream)
    except Exception as exc:  # noqa: BLE001
        log.warning("WS proxy to %s failed: %s", target, exc)
        try:
            await websocket.close(code=1011)
        except Exception:  # noqa: BLE001
            pass


async def _ws_pump(client: WebSocket, upstream) -> None:
    """Pump frames both ways until either side closes."""

    async def client_to_upstream() -> None:
        try:
            while True:
                msg = await client.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if (text := msg.get("text")) is not None:
                    await upstream.send(text)
                elif (data := msg.get("bytes")) is not None:
                    await upstream.send(data)
        except Exception:  # noqa: BLE001
            pass

    async def upstream_to_client() -> None:
        try:
            async for m in upstream:
                if isinstance(m, (bytes, bytearray)):
                    await client.send_bytes(bytes(m))
                else:
                    await client.send_text(m)
        except Exception:  # noqa: BLE001
            pass

    t1 = asyncio.create_task(client_to_upstream())
    t2 = asyncio.create_task(upstream_to_client())
    _done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    for closer in (upstream.close, client.close):
        try:
            await closer()
        except Exception:  # noqa: BLE001
            pass
