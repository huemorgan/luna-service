# 051 — Error tracking: unified error view + ingest table

**Repo:** luna-service (private control plane) · **Version bump:** per repo
convention (pyproject stays 0.1.0; version-per-commit not used here).
**Pairs with:** luna-plugins `plans/007-error-tracking/PLAN.md` (the capture
side inside plugin-feedback). This plan owns the **table, ingest endpoint,
self-tracking, and the admin "Error Tracking" left-pane view**.

## Goal

A single place to see **every** issue across the Luna runtime — agent-side
exceptions/timeouts, browser UI failures (JS errors, page-not-loaded, failed
fetches), and the control plane's own edge failures (502s, proxy read
timeouts, wake failures) — each with enough context to track it down:
what, where, which agent/account, when (source time + receive time), the
route/target, HTTP status, latency, stack, breadcrumbs, image version, region.

Two writers, one table:
1. **plugin-feedback** (agents + browsers) → `POST /api/agent/errors`
   (gateway token, agent resolved server-side). See plan 007.
2. **luna-service itself** → in-process `record_error_event(...)` at the proxy
   / wake / unhandled-exception sites it already logs. No HTTP hop.

## Non-goals

- No changes to feedback tickets (`feedback_tickets` / `feedback_messages`).
- Not an APM/tracing system — flat events + fingerprint grouping, not spans.
- No agent-DB storage — all error state lives on the control plane (mirrors
  the feedback-ticket decision).

## Data model — `error_events`

New table in `cloud/db/models.py` + Alembic migration. Mirrors
`FeedbackTicket`'s FK/denormalization discipline (`agent_id` ON DELETE SET
NULL, denormalized `account_id`).

| column         | type            | notes |
|----------------|-----------------|-------|
| id             | UUID pk         | |
| source         | text            | `agent` \| `ui` \| `service` |
| agent_id       | UUID null FK    | agents, ON DELETE SET NULL (null for `service`/OSS) |
| account_id     | UUID null       | denormalized at ingest for admin filtering |
| kind           | text            | `js_error`, `unhandled_rejection`, `page_load_failed`, `resource_error`, `fetch_error`, `http_5xx`, `timeout`, `proxy_502`, `proxy_read_timeout`, `agent_wake_failed`, `plugin_exception`, `llm_timeout`, `embed_error`, `agent_report`, `unhandled_exception` |
| severity       | text            | `info` \| `warning` \| `error` \| `critical` |
| message        | text            | short, human-readable |
| fingerprint    | text (indexed)  | stable group hash: `sha1(kind + normalized_message + route/target)` — normalize out ids/uuids/numbers |
| context        | JSONB           | url, route, method, status, target, latency_ms, stack, user_agent, breadcrumbs, plugin, turn_id, session_id, image_version, region, occurred_at |
| occurred_at    | timestamptz null| source/client time |
| created_at     | timestamptz     | control-plane receive time |

Indexes: `(fingerprint)`, `(source, created_at)`, `(agent_id, created_at)`,
`(severity, created_at)`, `(kind, created_at)`. Raw rows kept; grouping is a
query (count + first/last seen per fingerprint), so no lossy pre-aggregation.

Retention: `ERROR_RETENTION_DAYS` (default 60). Prune probabilistically on
ingest (~1% of accepted batches also run the `DELETE … WHERE created_at <
cutoff`) so there is no scheduler dependency; the `created_at` composite
indexes make the delete cheap.

## Endpoints

**Agent-facing** — new `cloud/api/error_agent_routes.py`, modeled on
`feedback_agent_routes.py`:
- `POST /api/agent/errors` — gateway-token auth (`verify_token` → Agent),
  accepts a **batch** (`{events: [...]}`), enriches each with
  `agent_id/account_id/image_version/region/created_at`, computes
  `fingerprint`, bulk-inserts. Returns **202** (fire-and-forget). Mounted also
  under `/proxy` like the feedback route.
- Rate limit per agent / trailing 24h via DB count (multi-worker safe), higher
  than feedback's cap (errors are bursty) — e.g. `MAX_ERROR_EVENTS_PER_DAY`
  with server-side sampling once exceeded, and a `429`-free drop (just don't
  insert; count is advisory). Log the drop.
- Payload hardening: whitelist `kind` (unknown values → `agent_report`, keep
  the original in context), clamp `severity` to the enum, cap batch ≤ 50
  events, message ≤ 500 chars, stack ≤ 16 KB, breadcrumbs ≤ 20 entries —
  truncate, don't reject (client data must never 422 the fire-and-forget path).

**Admin-facing** — new `cloud/api/error_routes.py` (`require_admin`),
`prefix="/api/admin/errors"`:
- `GET /` — grouped list (by fingerprint): count, first/last seen, top
  kind/severity, sample message, affected agents. Filters: source, severity,
  kind, agent_id, account_id, time range, free-text.
- `GET /{fingerprint}` — the group's recent raw events with full context.
- `GET /events/{id}` — a single event's full context (stack, breadcrumbs).
- `POST /{fingerprint}/resolve` (optional) — mark a group acknowledged/muted.
  If implemented it needs a tiny `error_group_state` table keyed by
  fingerprint (state, resolved_by, resolved_at); raw events stay immutable.

## Self-tracking (luna-service writes its own errors)

New `cloud/observability/error_sink.py` with
`async record_error_event(*, source="service", kind, severity, message,
context)` — direct DB insert, best-effort (swallows its own failures, never
breaks the request). Wire it into **existing** log sites, don't re-instrument:
- `cloud/api/proxy.py` — the `ReadTimeout` / `ReadError` / `RemoteProtocolError`
  warnings (→ `proxy_read_timeout` / `proxy_502`) and any 502 responses.
- Agent wake failures (→ `agent_wake_failed`).
- A FastAPI exception handler / middleware for unhandled 5xx
  (→ `unhandled_exception`).

Storm guard (mandatory, not optional): per-fingerprint in-process throttle
(~10/min) and drop-immediately when the DB itself is unavailable — no retry,
no queue. An incident that 500s every request must not amplify DB load through
its own error sink; when the sink drops, bump a process-local counter and log
one line per minute at most.

## Admin UI — "Error Tracking" left-pane section

`cloud/ui/src/pages/admin/`, nav in `AdminLayout.tsx`.
- Add a nav entry. Given it spans services + agents + edge, put it at top level
  in `NAV_TOP` (not under Services): `{ to: '/admin/errors', label: 'Error
  Tracking', icon: Bug }` (lucide `Bug` or `AlertTriangle`; `MessageSquare
  Warning` is already taken by Feedback).
- New `ErrorsPage.tsx` — the unified view:
  - **Top:** filters (source / severity / kind / agent / time) + a small
    volume sparkline per severity.
  - **Grouped list:** one row per fingerprint — severity chip, kind, message,
    count, last-seen, affected-agents count, source badge (ui/agent/service).
    Sorted by last-seen or count.
  - **Detail drawer:** click a group → recent events; each event shows the
    full context: route/url, method, HTTP status, target, latency, stack
    (monospace, scrollable), breadcrumbs timeline, agent + account +
    image_version + region, occurred_at vs created_at.
  - Everything needed to reproduce and fix, on one screen — that is the point.
- Register the route in the admin router alongside the other pages.

## Phases

- **P1 — Table + migration.** `error_events` model, Alembic, indexes,
  retention prune. Unit tests for fingerprint normalization.
- **P2 — Agent ingest endpoint.** `error_agent_routes.py`, batch insert,
  enrichment, rate-limit/sampling. Tests mirror `test_feedback.py`
  (cross-agent isolation, token auth, 202, batch).
- **P3 — Self-tracking sink.** `error_sink.record_error_event`, wire proxy +
  wake + unhandled-exception sites. Test that a forced proxy timeout writes a
  row.
- **P4 — Admin API.** `error_routes.py` grouped list + detail, filters,
  `require_admin`. Tests.
- **P5 — Admin UI.** `ErrorsPage.tsx` + nav entry + detail drawer.
- **P6 — Dojo + live browser test.** Drive the plugin (007) to emit each kind,
  force a real 502, confirm all three sources render in one view with full
  context. Screenshots. EXECUTION-SUMMARY.md.

## Testing (dojo, mandatory live walkthrough)

Scenario `051-error-tracking`: with a hosted agent + plugin-feedback 0.2.0,
trigger a UI JS error, a page-load 502 (stop the agent mid-load), an agent
plugin exception, and a proxy read timeout. Open `/admin/errors`; verify four
grouped entries across sources `ui`/`agent`/`service`, each drill-down showing
stack/breadcrumbs/agent/timing. Verify filters and grouping. Also include an
**agent-side unhandled 5xx** (e.g. a simulated DB-connect failure — the
2026-07-19 approval-500 incident, asyncpg connect errors on the agent's
approvals API, is the reference case) and verify it arrives via 007's log
handler with the traceback intact.

## Risks

- **Ingest abuse / volume** — a looping client could flood. Mitigate with
  client + server rate-limit, fingerprint dedupe, sampling past the cap, and a
  bounded batch size. The 256MB tenant DB is separate; this writes the
  control-plane DB — watch row growth, hence retention prune in P1.
- **Cross-session working tree** — luna-service commonly carries another
  session's uncommitted WIP (e.g. proxy.py holding-page). Stage only this
  plan's hunks; never disturb unrelated changes.
- **PII in stacks/URLs** — scrub is primarily client-side (007); server also
  strips obvious token patterns before store.

## Arch sync

Add an "Error tracking" note to `vision/architecture2.md` (or the control-plane
architecture doc): the `error_events` table, the two writers (agent via
`/api/agent/errors`, service in-process), and the admin view. Cross-link plan
007.
