"""WhatsApp gateway monitoring — admin proxy to luna-wa-gateway (plan 034).

The gateway's ``GET /stats`` is admin-key protected; the key lives only in
control-plane config and never reaches the browser. Responses are cached
in-process for a few seconds so N polling admin tabs produce at most one
upstream request per TTL window.
"""

from __future__ import annotations

import logging
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from cloud import config
from cloud.auth.deps import require_admin
from cloud.db.models import Agent, User
from cloud.db.session import get_session as get_db_session
from cloud.whatsapp import provision

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/whatsapp", tags=["whatsapp"])

STATS_TIMEOUT_S = 5.0
STATS_CACHE_TTL_S = 12.0

# (expires_at_monotonic, payload) — payload is the full route response.
_stats_cache: tuple[float, dict] | None = None


def _gateway_config() -> tuple[str, str]:
    s = config.get_settings()
    return s.whatsapp_gateway_url.rstrip("/"), s.whatsapp_gateway_admin_key


async def _fetch_stats(url: str, admin_key: str) -> dict:
    """One upstream call, mapped to a never-5xx envelope."""
    try:
        async with httpx.AsyncClient(timeout=STATS_TIMEOUT_S) as client:
            resp = await client.get(
                f"{url}/stats", headers={"x-admin-key": admin_key}
            )
    except Exception as exc:  # DNS, timeout, refused — the page shows Offline
        log.warning("whatsapp.stats_unreachable url=%s err=%s", url, exc)
        return {"configured": True, "reachable": False}

    if resp.status_code == 401:
        return {"configured": True, "reachable": True, "authorized": False}
    if resp.status_code != 200:
        log.warning("whatsapp.stats_bad_status status=%s", resp.status_code)
        return {"configured": True, "reachable": False}
    try:
        stats = resp.json()
    except ValueError:
        return {"configured": True, "reachable": False}
    return {
        "configured": True,
        "reachable": True,
        "authorized": True,
        "stats": stats,
    }


@router.get("/stats")
async def gateway_stats(admin=Depends(require_admin)):
    global _stats_cache
    url, admin_key = _gateway_config()
    if not url:
        return {"configured": False}

    now = time.monotonic()
    if _stats_cache and _stats_cache[0] > now:
        return _stats_cache[1]

    payload = await _fetch_stats(url, admin_key)
    # QR is served through our own authed proxy — the admin key never
    # appears in a browser-visible URL.
    payload["qr_url"] = (
        "/api/admin/whatsapp/qr" if payload.get("stats", {}).get("has_qr") else None
    )
    _stats_cache = (now + STATS_CACHE_TTL_S, payload)
    return payload


@router.get("/qr")
async def gateway_qr(admin=Depends(require_admin)):
    """Server-side proxy of the gateway's QR page (it self-refreshes, so
    each refresh comes back through this authed route)."""
    from fastapi.responses import HTMLResponse

    url, admin_key = _gateway_config()
    if not url:
        return HTMLResponse("<p>WhatsApp gateway not configured.</p>", status_code=503)
    try:
        async with httpx.AsyncClient(timeout=STATS_TIMEOUT_S) as client:
            resp = await client.get(f"{url}/qr", params={"key": admin_key})
    except Exception:
        return HTMLResponse("<p>Gateway unreachable.</p>", status_code=502)
    return HTMLResponse(resp.text, status_code=resp.status_code)


async def _accounts_by_id() -> dict[str, dict]:
    """Per-account state from the gateway's /stats (multi-account), keyed by
    account_id. Empty when unconfigured/unreachable — the table degrades to
    readiness-only."""
    url, admin_key = provision.gateway_config()
    if not url:
        return {}
    payload = await _fetch_stats(url, admin_key)
    accounts = (payload.get("stats") or {}).get("accounts") or []
    return {a.get("account_id"): a for a in accounts if a.get("account_id")}


@router.get("/instances")
async def whatsapp_instances(admin=Depends(require_admin)):
    """Per-Luna WhatsApp state: plugin membership + the agent's own gateway
    account (account_id == agent.slug)."""
    accounts = await _accounts_by_id()
    async with get_db_session() as db:
        agents = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
        rows = []
        for a in agents:
            acct = accounts.get(a.slug)
            rows.append({
                "agent_id": str(a.id),
                "name": a.name,
                "slug": a.slug,
                "status": a.status,
                "plugin_installed": "plugin-whatsapp"
                in ((a.config_overrides or {}).get("installed_plugins") or []),
                "account": {
                    "status": acct.get("status"),
                    "connected": acct.get("connected"),
                    "self_jid": acct.get("self_jid"),
                    "has_qr": acct.get("has_qr"),
                    "messages_24h_in": acct.get("messages_24h_in"),
                    "messages_24h_out": acct.get("messages_24h_out"),
                    "sent_today": acct.get("sent_today"),
                    "daily_cap": acct.get("daily_cap"),
                } if acct else None,
            })
        return rows


async def _get_agent(agent_id: str) -> Agent:
    try:
        aid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        return agent


@router.post("/instances/{agent_id}/connect")
async def connect_instance(agent_id: str, admin: User = Depends(require_admin)):
    """Give this Luna its own WhatsApp account: gateway account + vault secret
    + plugin install. Restart-free; idempotent."""
    global _stats_cache
    agent = await _get_agent(agent_id)
    url, _ = provision.gateway_config()
    if not url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp gateway not configured")
    try:
        result = await provision.connect_agent(agent, admin_email=admin.email)
    except Exception as exc:
        log.error("whatsapp.connect failed agent=%s err=%s", agent.slug, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gateway connect failed: {exc}")
    _stats_cache = None  # the new account should appear on the next poll
    return {"ok": True, **result, "qr_path": f"/api/admin/whatsapp/instances/{agent_id}/qr"}


@router.delete("/instances/{agent_id}/connect")
async def disconnect_instance(agent_id: str, admin: User = Depends(require_admin)):
    global _stats_cache
    agent = await _get_agent(agent_id)
    try:
        result = await provision.disconnect_agent(agent)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gateway disconnect failed: {exc}")
    _stats_cache = None
    return {"ok": True, **result}


@router.get("/instances/{agent_id}/qr")
async def instance_qr(agent_id: str, admin=Depends(require_admin)):
    """This Luna's own QR, proxied server-side (admin key stays here)."""
    agent = await _get_agent(agent_id)
    try:
        resp = await provision.fetch_account_qr(agent.slug, fmt="html")
    except Exception:
        return HTMLResponse("<p>Gateway unreachable.</p>", status_code=502)
    return HTMLResponse(resp.text, status_code=resp.status_code)


# ── Phase 3: fleet backfill + reconcile ──────────────────────────────────────

@router.post("/env/backfill")
async def whatsapp_env_backfill(dry_run: bool = True, admin: User = Depends(require_admin)):
    """Push LUNA_WHATSAPP_GATEWAY_URL to Fly machines missing it, and report
    gateway⇄agents drift (accounts with no matching agent).

    Unlike the plan-029 gateway backfill this pushes ONLY the one WhatsApp var
    (update_machine_env merges), so there is no token rotation involved. A
    machine update restarts it in place. dry_run=true reports only.
    """
    import os

    url, _ = provision.gateway_config()
    if not url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp gateway not configured")

    # Drift: gateway accounts that match no agent slug (account `default` is
    # the legacy pre-multiluna number and is expected to be unmatched).
    orphans: list[str] = []
    try:
        resp = await provision._gateway("GET", "/accounts")
        payload = resp.json() if resp.status_code == 200 else {}
        accounts = payload.get("accounts") if isinstance(payload, dict) else payload
    except Exception:
        accounts = None

    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.runtime_ref.is_not(None))
        )).scalars().all()
        slugs = {a.slug for a in agents}
        targets = [(a.slug, a.runtime_ref, a.runtime_kind) for a in agents]
    if accounts is not None:
        orphans = [a["account_id"] for a in accounts
                   if a.get("account_id") not in slugs and a.get("account_id") != "default"
                   and a.get("status") != "disabled"]

    results: list[dict] = []
    updated = skipped = errored = 0
    if os.environ.get("FLY_API_TOKEN"):
        from cloud.runtime.fly_machines import FlyMachinesRuntime
        fly = FlyMachinesRuntime()
        for slug, ref, kind in targets:
            if not (kind or "").startswith("fly"):
                continue
            row: dict = {"slug": slug, "machine_id": ref}
            try:
                rec = await fly.describe(ref)
                if not rec:
                    row["status"] = "machine_gone"
                    errored += 1
                elif "LUNA_WHATSAPP_GATEWAY_URL" in ((rec.get("config") or {}).get("env") or {}):
                    row["status"] = "up_to_date"
                    skipped += 1
                elif dry_run:
                    row["status"] = "would_update"
                else:
                    await fly.update_machine_env(ref, {"LUNA_WHATSAPP_GATEWAY_URL": url})
                    row["status"] = "updated"
                    updated += 1
            except Exception as exc:  # noqa: BLE001 — per-machine, never abort the run
                log.error("whatsapp backfill failed for %s: %s", slug, exc)
                row["status"] = f"error: {type(exc).__name__}"
                errored += 1
            results.append(row)
    else:
        results.append({"status": "fly_not_configured"})

    return {
        "dry_run": dry_run,
        "updated": updated, "skipped": skipped, "errored": errored,
        "machines": results,
        "orphan_accounts": orphans,
    }


# ── Public inbound relay ─────────────────────────────────────────────────────
# The gateway POSTs each account's inbound envelope here (this URL is what
# connect registers as the account's inbound_url). We forward the RAW bytes +
# HMAC headers to the tenant machine — Fly routing header, wake-on-sleep —
# and the plugin verifies the signature itself. No session auth by design:
# a forged request without the account secret dies at the plugin's HMAC check.

RELAY_TIMEOUT_S = 120.0  # gateway tolerates slow (cold-start) turns up to 120s


relay_router = APIRouter(tags=["whatsapp-relay"])


@relay_router.post("/api/webhooks/whatsapp/{agent_slug}/inbound")
async def whatsapp_inbound_relay(agent_slug: str, request: Request):
    import os

    from cloud.api.proxy import _try_wake_agent
    from cloud.runtime.proxy_secret import derive_proxy_secret

    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.slug == agent_slug)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown agent")
        owner = (await db.execute(
            select(User).where(User.id == agent.creator_id)
        )).scalar_one_or_none()

    if not (agent.internal_url or "").startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent has no machine")

    raw = await request.body()
    root_secret = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")
    headers = {
        "content-type": request.headers.get("content-type", "application/json"),
        "x-wa-timestamp": request.headers.get("x-wa-timestamp", ""),
        "x-wa-signature": request.headers.get("x-wa-signature", ""),
        "x-luna-proxy-secret": derive_proxy_secret(root_secret, str(agent.id)),
        "x-luna-user": (owner.email if owner else "") or "",
    }
    if agent.runtime_ref:
        headers["fly-force-instance-id"] = agent.runtime_ref
    target = f"{(agent.internal_url or '').rstrip('/')}/api/p/plugin-whatsapp/inbound"

    async def _send():
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(RELAY_TIMEOUT_S, connect=10)
        ) as client:
            return await client.post(target, content=raw, headers=headers)

    try:
        resp = await _send()
    except httpx.ReadTimeout:
        # NOT retried — the turn may still be running; a retry risks a double reply.
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Agent turn timed out")
    except httpx.HTTPError:
        # Machine asleep/unreachable — wake it and retry once.
        if not await _try_wake_agent(agent):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Agent unreachable")
        try:
            resp = await _send()
        except Exception:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Agent unreachable after wake")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )
