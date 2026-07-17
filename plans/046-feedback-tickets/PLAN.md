# 046 — Feedback tickets (agent + owner → admin, threaded)

**Status:** PLANNED (2026-07-17 — the `EXECUTED` header was aspirational; no
service-side code had landed. Migration is `0011_feedback_tickets` because
`0010` is the billable-event channel column. Being executed now.)
**Produces version:** none in this planning slice
**Companions:** `huemorgan2/plugin-feedback` 0.1.0 (built against this contract)

## Context

Owners have no channel to tell the Luna team anything — "this is expensive",
"this is broken", "I'm frustrated" all die in the agent's chat. We want:

1. The agent files feedback on the owner's behalf (direct complaints → the agent
   offers and drafts; indirect frustration → the agent files it itself, with the
   conversation as reference or its own summary of what went wrong).
2. The owner writes feedback directly in a **Feedback** sidebar pane inside
   their Luna, sees admin responses there, and replies — a threaded
   conversation, because admins may need to ask follow-up questions.
3. Admins triage and answer everything from a **Feedback** page in the
   luna-service admin left nav.
4. When an admin replies, the agent learns about it (so it can read the ticket
   and relay/act), not just the pane.

All ticket state lives in the control-plane DB (`cloud/`), never in the
agent's own Postgres. The plugin is stateless; its pane and tools proxy to the
control plane.

## Decision

Self-contained feature in the control plane — no external microservice, no
per-feature provisioning. Agents authenticate with the **existing gateway
tenant token** (`Authorization: Bearer lsv1-…` or `X-Luna-Gateway-Token`), the
same channel scheduler/whatsapp connect uses. `verify_token` resolves the
`Agent` server-side; a caller can never name or read another agent's tickets.

The plugin (huemorgan2/plugin-feedback, already built) codes against the agent
API below; ship the service side to this exact contract.

## Data model (`cloud/db/models.py`, migration `0011_feedback_tickets`)

`feedback_tickets`
- `id UUID pk` · `agent_id UUID FK agents ON DELETE SET NULL` (mirror
  `RelayDelivery`; agents soft-delete) · `account_id UUID nullable` (denorm at
  create for admin filtering)
- `origin text` — `user` (owner wrote it: pane form, or dictated to the agent)
  | `agent` (agent-initiated from indirect signals)
- `category text` — `cost | bug | frustration | feature | praise | other`
- `severity text` — `low | normal | high`
- `status text` — `open` (new, or client replied) | `answered` (last word is
  admin's) | `closed`
- `title text` · `context JSONB` (client-supplied, see below, server-enriched
  with `slug`, `image_version`, `runtime_ref` from the resolved Agent row)
- `created_at / updated_at / last_admin_reply_at / last_client_reply_at /
  agent_read_at / closed_at timestamptz`
- Indexes: `(status, updated_at desc)`, `agent_id`, `created_at`, and
  `ix_feedback_tickets_agent_updated (agent_id, updated_at desc)` — the
  `/updates` unread poll filters by `agent_id` then compares
  `last_admin_reply_at > agent_read_at` in the query; the composite index
  serves the agent-scoped scan (the read-marker comparison is a residual
  filter, not indexable as a partial because both columns move).

`feedback_messages`
- `id UUID pk` · `ticket_id UUID FK feedback_tickets ON DELETE CASCADE`
- `author text` — `user | agent | admin`
- `admin_user_id UUID FK users ON DELETE SET NULL` (when author=admin)
- `body text` · `meta JSONB` (e.g. `{conversation_excerpt: [...], technical:
  {...}}` on the opening message) · `created_at timestamptz`
- Index: `(ticket_id, created_at)`.

The opening message is a `feedback_messages` row too (author = origin); the
ticket row holds only summary/state. `context` JSONB from the client carries:
`agent_name, owner_name, mission, conversation_id, client_time` (exact UTC
ISO timestamp at the client — server also stamps `created_at` on receipt),
`host` (`LUNA_HOST_NAME`), `plugin_version`. Server enrichment beats client
claims where they overlap; keep both (client block under `context.client`,
server block under `context.server`) so drift is itself diagnostic.

## Agent API (`cloud/api/feedback_agent_routes.py`, token auth)

- `POST /api/agent/feedback/tickets`
  `{origin, category, severity?, title, body, context?, conversation_excerpt?,
  technical?}` → `201 {id, status, created_at}`. `body` becomes the opening
  message; `conversation_excerpt` (list of `{role, content, created_at}`) and
  `technical` (free dict: error text, plugin versions, repro) land in the
  opening message's `meta`.
- `GET /api/agent/feedback/tickets?limit=&offset=` → `{tickets: [{id, title,
  category, origin, severity, status, created_at, updated_at,
  last_admin_reply_at, unread}]}` — `unread` = `last_admin_reply_at >
  agent_read_at` (null-safe). Newest-updated first.
- `GET /api/agent/feedback/tickets/{id}?mark_read=1` → `{ticket, messages}`.
  `mark_read=1` sets `agent_read_at = now()` (both the pane and the agent tools
  use it; one read marker per install is deliberate — the pane and the agent
  serve the same owner).
- `POST /api/agent/feedback/tickets/{id}/replies` `{author: user|agent, body}`
  → message row; sets `last_client_reply_at`, flips `answered → open` (a client
  reply reopens the conversation for triage). Replying to `closed` is allowed
  and reopens the same way.
- `GET /api/agent/feedback/updates` → `{unread: [{id, title,
  last_admin_reply_at}]}` — cheap poll the plugin calls (throttled) from
  `prompt_sections()`. Single query: `WHERE agent_id = <resolved> AND
  last_admin_reply_at IS NOT NULL AND (agent_read_at IS NULL OR
  last_admin_reply_at > agent_read_at)`, served by
  `ix_feedback_tickets_agent_updated`.

**Shared `agent_read_at` (confirmed deliberate for v1):** the pane's
`GET /tickets/{id}?mark_read=1` and the agent's `feedback_ticket_get` both stamp the
same `agent_read_at`. Consequence: if the owner opens the pane first, the
agent's `/updates` poll goes quiet and the one-line prompt note never fires
for that ticket. Accepted — the pane and the agent serve the same owner, and
the owner has already seen the reply in that case. Revisit only if we split
per-surface read state.

404 (not 403) for a ticket id that exists under another agent — don't leak
existence.

## Admin API (`cloud/api/feedback_routes.py`, `prefix="/api/admin/feedback"`,
`Depends(enforce_same_origin)` + `require_admin`)

- `GET /tickets?status=&category=&origin=&agent=&q=&limit=&offset=` — joined
  with agent name/slug + account slug; unanswered-first default sort
  (`status=open`, oldest `updated_at` first).
- `GET /tickets/{id}` — full thread + context JSONB pretty view.
- `POST /tickets/{id}/reply` `{body}` — author=admin, stamps `admin_user_id`,
  sets `last_admin_reply_at`, status → `answered`.
- `POST /tickets/{id}/status` `{status: open|closed}`.
- Optional later: `_audit(...)` rows on admin actions, matching admin_routes.

Register both routers in `cloud/main.py`; include the agent router **also
under `prefix="/proxy"`** (like `scheduler_agent_router`, main.py:233-242) —
machines carry `LUNA_GATEWAY_URL = "<host>/proxy"` and the plugin calls
`{LUNA_GATEWAY_URL}/api/agent/feedback/...`.

## Admin UI

`cloud/ui/src/pages/admin/FeedbackPage.tsx` + route under `/admin` in
`App.tsx` + `SERVICE_ITEMS` nav entry (lucide `MessageSquareWarning` or
similar). Columns: status pill, category, title, agent (name/slug), origin
badge (owner vs agent-filed), updated, unread-by-us indicator
(`last_client_reply_at > last_admin_reply_at`). Detail drawer: thread
(admin replies inline), context panel (mission, conversation excerpt,
technical block, machine/slug/image_version, client vs server timestamps),
status controls. No new stack — same fetch-to-`/api/admin/...` pattern as
ModelsPage.

## How the agent learns about admin replies

No push needed for v1. The plugin polls `GET /api/agent/feedback/updates` at
most every ~10 minutes (throttled inside `prompt_sections()`, 3s timeout,
fail-silent) and injects a one-line prompt note when something is unread; the
pane refreshes on open and on its own poll. If later we want instant push,
reuse the relay forwarder to POST to
`{agent.internal_url}/api/p/plugin-feedback/notify` — out of scope here.

## Security and data concerns

- Tenant token resolves the agent server-side; ticket queries are always
  `WHERE agent_id = <resolved>`; cross-agent ids return 404.
- Conversation excerpts are owner conversation content stored on the control
  plane. The plugin only attaches them when the agent explicitly opts in
  (`include_conversation`), and the tool is `prompt_always` — the owner sees
  and approves the exact payload (the approval card is the "feedback box").
  Admin UI must treat excerpts as sensitive: admin-only, no export endpoint.
- No secrets in `context`/`technical`; the plugin strips env-var-looking
  values (`*_KEY`, `*_SECRET`, `*_TOKEN` patterns) before sending; server may
  re-scrub defensively.
- Rate-limit `POST` create/reply per agent (30/day create, 120/day reply) to
  keep a misbehaving agent from flooding triage. Enforced with a DB count over
  the trailing 24h (`SELECT count(*) … WHERE agent_id=… AND created_at >
  now() - interval '1 day'`), NOT an in-process counter — the control plane
  runs multiple uvicorn workers, so an in-memory limit would be per-worker and
  reset on deploy. Over-limit returns `429`.
- Deleting an agent keeps tickets (`SET NULL`) — feedback history outlives the
  install, like relay deliveries.

## Out of scope (v1)

- Email/Slack notification to admins on new tickets (add to the reconciler
  later if triage lags).
- Push notifications to the agent (relay path sketched above).
- Attachments.
