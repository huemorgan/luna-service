# 051 — Unified error tracking: execution summary

Date: 2026-07-21 · Branch: main (commits 9219eb1, 760216a) · Deployed: Render dep-d9fpae2ta46c73cnod6g (live)

## What was accomplished

- **`error_events` table** (migration 0012): source / agent_id (FK SET NULL) /
  account_id / kind / severity / message / fingerprint / context JSONB /
  occurred_at / created_at, with five query indexes (fingerprint,
  source+created, agent+created, severity+created, kind+created).
- **Server-side fingerprinting** (`cloud/observability/error_sink.py`):
  sha1(kind + normalized message + normalized route); normalization collapses
  UUIDs, long hex, and digit runs so retries group. 15-kind vocabulary;
  unknown kinds are folded to `agent_report` with `original_kind` preserved.
- **Agent ingest** `POST /api/agent/errors` (+ `/proxy` mount), gateway-token
  auth, batch ≤50, always 202 for authed callers, hardening for every field,
  server-resolved identity (client identity claims ignored), daily cap
  (`MAX_ERROR_EVENTS_PER_DAY`, default 2000/agent) with headroom truncation,
  probabilistic retention pruning (`ERROR_RETENTION_DAYS`, default 60).
- **Service self-tracking** (`record_error_event`): never-raises sink with a
  per-fingerprint storm guard (10/min); wired into `cloud/main.py` as a global
  unhandled-exception handler (kind `unhandled_exception`, critical) and into
  `cloud/api/proxy.py` at 8 failure points (`proxy_502`, `proxy_read_timeout`,
  `agent_wake_failed`).
- **Admin API** `/api/admin/errors`: fingerprint-grouped list with filters
  (source/severity/kind/agent/account/q/hours/sort), per-severity totals,
  group detail (last 50 events), single-event lookup.
- **Admin UI**: left-pane **Error Tracking** section (Bug icon) —
  `ErrorsPage.tsx` with severity chips, filters, grouped table, and a detail
  drawer (stack, breadcrumbs, route/status/latency, agent/account, raw
  context).
- **Reporter injection** (commit 760216a): `_rewrite_html_paths` adds
  `<script src="/a/{slug}/api/p/plugin-feedback/reporter.js" defer>` to every
  proxied page — pairs with luna-plugins plan 007 (plugin-feedback 0.2.0).
  404s silently when the plugin is absent, so OSS/old agents are unaffected.

## Tests

17 new tests in `cloud/tests/test_errors.py` (fingerprinting, clamps, ingest
auth/enrichment/caps, sink storm guard, unhandled-exception capture, admin
grouping/filters/authz) — all passing. Pre-existing failures
(`test_gemini_chat_route_and_adapter`, `test_resolve_falls_back_to_seed`)
verified present at HEAD before this work and left untouched.

## Production verification (dojo)

See `tests/051-error-tracking/dojo.md`. Highlights: migration applied on
deploy; `/api/admin/errors` live; a real `proxy_502`
("Proxy stream broke (RemoteProtocolError)", source=service, agent resolved)
was captured organically during the plugin-install machine restart and
appeared grouped in the admin view.

## Deviations from plan

- `POST /{fingerprint}/resolve` (optional in plan) skipped — needs an
  `error_group_state` table; revisit if triage state is wanted.
- UI-source ingest arrives via plugin-feedback's `/errors` route (agent
  forwards with its gateway token), not via a direct browser→service
  endpoint — keeps the gateway token server-side and adds zero core changes.
