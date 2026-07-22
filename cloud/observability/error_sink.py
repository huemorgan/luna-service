"""Plan 051 — error-event fingerprinting, payload hardening, and the
service-side sink.

Shared by the agent ingest endpoint (`cloud/api/error_agent_routes.py`) and
luna-service's own writers. `record_error_event` is strictly best-effort: it
must never raise into a request path and must never amplify an incident's DB
load through its own storm (per-fingerprint throttle, drop-on-DB-failure,
at most one log line per minute about drops).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

KINDS = {
    "js_error", "unhandled_rejection", "page_load_failed", "resource_error",
    "fetch_error", "http_5xx", "timeout", "proxy_502", "proxy_read_timeout",
    "agent_wake_failed", "plugin_exception", "llm_timeout", "embed_error",
    "agent_report", "unhandled_exception", "gateway_auth",
}
SEVERITIES = {"info", "warning", "error", "critical"}
SOURCES = {"agent", "ui", "service"}

MAX_MESSAGE_CHARS = 500
MAX_STACK_CHARS = 16 * 1024
MAX_BREADCRUMBS = 20

# Fingerprint normalization: collapse anything instance-specific so the same
# defect groups regardless of ids, ports, timings, or addresses.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{12,}\b")
_NUM_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = _UUID_RE.sub("#", text or "")
    text = _HEX_RE.sub("#", text)
    text = _NUM_RE.sub("#", text)
    return _WS_RE.sub(" ", text).strip().lower()


def compute_fingerprint(kind: str, message: str, route: str | None = None) -> str:
    """Stable group hash: sha1(kind + normalized message + normalized route)."""
    basis = f"{kind}\n{_normalize(message)}\n{_normalize(route or '')}"
    return hashlib.sha1(basis.encode("utf-8", errors="replace")).hexdigest()


def clamp_kind(kind: str | None) -> tuple[str, str | None]:
    """Whitelist `kind`; unknown values become agent_report and the original
    is returned for preservation in context (truncate, never reject)."""
    k = (kind or "").strip()
    if k in KINDS:
        return k, None
    return "agent_report", (k[:100] or None)

def clamp_severity(severity: str | None) -> str:
    s = (severity or "").strip()
    return s if s in SEVERITIES else "error"


def harden_context(context: dict | None) -> dict | None:
    """Cap the unbounded fields of a client-supplied context block."""
    if not isinstance(context, dict):
        return None
    ctx = dict(context)
    stack = ctx.get("stack")
    if isinstance(stack, str) and len(stack) > MAX_STACK_CHARS:
        ctx["stack"] = stack[:MAX_STACK_CHARS] + "\n…[truncated]"
    crumbs = ctx.get("breadcrumbs")
    if isinstance(crumbs, list) and len(crumbs) > MAX_BREADCRUMBS:
        ctx["breadcrumbs"] = crumbs[-MAX_BREADCRUMBS:]
    return ctx


def clamp_message(message: str | None) -> str:
    msg = (message or "").strip() or "(no message)"
    return msg[:MAX_MESSAGE_CHARS]


def parse_occurred_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Service-side sink with storm guard.
#
# Per-fingerprint token bucket (~10/min) and process-local drop accounting.
# In-process state is fine here: the guard is about protecting *this* worker's
# DB pressure, not exact global limits.
# ---------------------------------------------------------------------------

_THROTTLE_PER_MIN = 10
_MAX_TRACKED_FINGERPRINTS = 1000

_buckets: dict[str, tuple[int, int]] = {}  # fingerprint -> (minute, count)
_dropped = 0
_last_drop_log = 0.0


def _throttled(fingerprint: str) -> bool:
    global _buckets
    minute = int(time.time() // 60)
    if len(_buckets) > _MAX_TRACKED_FINGERPRINTS:
        _buckets = {f: v for f, v in _buckets.items() if v[0] == minute}
    win, count = _buckets.get(fingerprint, (minute, 0))
    if win != minute:
        win, count = minute, 0
    _buckets[fingerprint] = (win, count + 1)
    return count >= _THROTTLE_PER_MIN


def _note_drop(reason: str) -> None:
    global _dropped, _last_drop_log
    _dropped += 1
    now = time.monotonic()
    if now - _last_drop_log >= 60.0:
        _last_drop_log = now
        log.warning("error sink dropped %d event(s) (last reason: %s)", _dropped, reason)
        _dropped = 0


async def record_error_event(
    *,
    kind: str,
    message: str,
    severity: str = "error",
    source: str = "service",
    context: dict | None = None,
    route: str | None = None,
    agent_id=None,
    account_id=None,
) -> None:
    """Insert one service-side error event. Never raises."""
    try:
        kind, original_kind = clamp_kind(kind)
        message = clamp_message(message)
        fingerprint = compute_fingerprint(kind, message, route)
        if _throttled(fingerprint):
            _note_drop("throttled")
            return

        ctx = harden_context(context) or {}
        if route and "route" not in ctx:
            ctx["route"] = route
        if original_kind:
            ctx["original_kind"] = original_kind

        from cloud.db import session as db_session
        from cloud.db.models import ErrorEvent

        async with db_session.get_session() as db:
            db.add(ErrorEvent(
                source=source if source in SOURCES else "service",
                agent_id=agent_id,
                account_id=account_id,
                kind=kind,
                severity=clamp_severity(severity),
                message=message,
                fingerprint=fingerprint,
                context=ctx or None,
                occurred_at=datetime.now(timezone.utc),
            ))
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — sink must never break a request
        _note_drop(f"{type(exc).__name__}: {exc}")
