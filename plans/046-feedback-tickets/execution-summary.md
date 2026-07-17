# 046 — Feedback tickets — execution summary

**Date:** 2026-07-17 · **Branch:** `046-feedback-tickets` → merged to `main` ·
**Companion:** `huemorgan2/plugin-feedback` 0.1.0 (already published, unchanged)

## What was accomplished

Shipped the control-plane side of feedback tickets — the service the
already-published plugin was written against. Nothing had actually landed
before (the plan's `EXECUTED` header was aspirational).

- **DB (`cloud/db/models.py`, migration `0011_feedback_tickets`):**
  `feedback_tickets` (agent_id FK ON DELETE SET NULL, denorm account_id,
  origin/category/severity/status, title, `context` JSONB, the timestamp set,
  indexes incl. `ix_feedback_tickets_agent_updated` for the unread poll) and
  `feedback_messages` (author user|agent|admin, admin_user_id, body, meta
  JSONB, cascade delete). Purely additive; no existing data touched.
- **Agent API (`cloud/api/feedback_agent_routes.py`)** — tenant-token auth
  (`verify_token`), mounted at `/api/agent/feedback` **and** `/proxy/...`:
  `POST /tickets`, `GET /tickets`, `GET /tickets/{id}?mark_read=`,
  `POST /tickets/{id}/replies`, `GET /updates`. Cross-agent id → 404 (no
  existence leak). Server enriches `context.server` with slug/image_version/
  runtime_ref; client block kept under `context.client`. Rate limits via 24h
  DB count: 30 creates/day, 120 replies/day → 429.
- **Admin API (`cloud/api/feedback_routes.py`, `/api/admin/feedback`)** —
  `require_admin` + `enforce_same_origin`: list with status/category/origin/
  agent/q filters (unanswered-first, joined to agent + account),
  detail+thread+context, `POST /tickets/{id}/reply` (author=admin → answered),
  `POST /tickets/{id}/status` (open|closed). Client reply reopens.
- **Admin UI (`cloud/ui/src/pages/admin/FeedbackPage.tsx`)** — nav entry under
  Services, filter bar, ticket table with origin/agent/status, detail drawer
  with threaded messages (owner/agent/team), technical + conversation-excerpt
  panels, context view, reply box, close/reopen. Route wired in `App.tsx`.
- Registered all three routers in `cloud/main.py`.

## Tests

- **Backend:** `cloud/tests/test_feedback.py`, 13 tests — create/list/get/
  reply/updates, cross-agent 404, `/proxy` alias, rate-limit 429, admin
  filters/reply/close-reopen, admin-only 403. Full suite green (681 passed).
- **Live integration (real plugin code vs. live local service on SQLite):**
  - `plugin_feedback.client` (HTTP layer) — create/list/get/reply/updates. ✓
  - `plugin_feedback.tools.register_tools` → real `feedback_ticket_send`
    handler with `written_by="agent"` → 201, `sent:true`. This is the exact
    path the agent runtime runs when the LLM files feedback on its own. ✓
  - Credential scrub verified: `lsv1-…` in body and `OPENAI_API_KEY=…` in
    `technical` both `[redacted]` by the plugin. ✓
  - Server `context.server` enrichment (slug/image_version/runtime_ref). ✓
- **Browser (real Chromium, admin UI):** agent-filed ticket shows in
  `/admin/feedback` with origin=agent; opened drawer; posted an admin reply →
  status flipped **open → answered**, thread shows "Luna team" message; the
  agent's `/updates` poll then reported it unread and cleared after read. ✓

## What we discovered along the way

- **No local Postgres/Docker on this machine.** Ran the walkthrough against a
  SQLite DB with the same JSONB/UUID `@compiles` shims the test suite uses,
  via a throwaway harness (`/tmp/fb_app.py`) that serves the real feedback +
  auth routers + built SPA but skips `cloud.main`'s lifespan (heavy
  Postgres-only seeds). Production is unaffected — the Dockerfile builds the
  UI fresh and runs `cloud.db.migrate` (Postgres) before boot.
- **UUID path params:** SQLite's UUID column rejects a `str`; string path ids
  are parsed with `uuid.UUID(...)` (malformed → 404). On Postgres this was
  latent but the cast is correct there too.
- **Naive/aware datetime compare:** SQLite drops tzinfo, so a freshly-set
  aware `agent_read_at` compared against a stored naive `last_admin_reply_at`
  raised. `_aware()` normalizes to UTC before comparing (`_unread`).
- **CSRF/same-origin:** `enforce_same_origin` compares request Origin to
  `base_url`; `127.0.0.1` ≠ `localhost` gave a local-only 403 on admin POSTs.
  Re-ran the browser via `localhost:8100` (matches default base_url). No prod
  impact.
- The plugin uses `LUNA_GATEWAY_URL` (= `<host>/proxy`), so the `/proxy`
  alias mount is load-bearing, not optional.

## Things to consider in the future

- **Server-side re-scrub (deferred).** The plan says the server *may* re-scrub
  credential-shaped strings defensively. Not implemented — the plugin's
  client/tool scrubs reliably (verified). Worth adding as defense-in-depth
  against a compromised/older plugin; port `plugin_feedback/context.py`
  regexes into the create/reply handlers.
- **LLM decision not exercised live.** The autonomous "LLM chooses to call
  `feedback_ticket_send`" step needs a fully-provisioned hosted Luna (Fly
  machine + injected gateway token), not runnable locally here. The exact tool
  handler it invokes *was* run against the live service, so only the model's
  choice is unverified.
- **Shared `agent_read_at`** (pane + agent share one read marker) is
  deliberate for v1 — see the note in `PLAN.md`. Revisit if per-surface unread
  is wanted.
- Out of scope (unchanged): email/Slack admin alerts on new tickets, push to
  the agent, attachments.

## Deploy

Render (`luna.com.ai`) auto-deploys on push to `main`. `cloud/Dockerfile`
rebuilds the UI and runs `python -m cloud.db.migrate` (applies 0011) before
uvicorn; a migration failure aborts the deploy and the old app keeps serving.
No new env vars. No version-surface bump (luna-service has no `__version__`).
