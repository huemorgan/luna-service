# 082 — luna-service-mobile: every Luna reports its chats to the control plane

Requested by roy (2026-09-27): "build a plugin on the marketplace, not in the luna core, call it
luna-service-mobile … ship lunas baked with it … create a plan, execute it and deploy to all machines."
Design background: luna-control `plans/002-real-app-on-luna-service/PLAN.md`.

## Problem

The Luna iPhone app needs one feed of every chat across a person's Lunas, with previews, unread
counts, pending approvals and a "working…" state, updated the moment something happens. luna-service
knows nothing about chats. Reading tenant databases was ruled out: one LISTEN connection per Luna
does not fit the tenant cluster (`max_connections = 103`, alert at 80, plans 073/074), and "working"
never touches the database. No polling anywhere.

## Design

1. **Control plane (luna-service, branch `chat-feed`, PR 2):** `chat_index` / `chat_events` /
   `chat_read_markers`, `POST /api/agent/chats/events` (gateway token, fire-and-forget like
   `/api/agent/errors`), `GET /api/feed`, `POST /api/feed/{agent}/{conversation}/read`,
   `GET /api/feed/stream` (SSE, fanned out across workers with `pg_notify` on luna-service's own DB).
   Already built and tested.
2. **Plugin `luna-service-mobile` (luna-marketplaces `marketplace-src/luna_service_mobile`):**
   subscribes to Luna's in-process bus and forwards small events. No tools, no routes, no tables.
   - `message.received` → user `message` event (web messages).
   - `agent.turn.started` / `agent.turn.ended` → `turn.started` / `turn.ended`; on `ended` it reads the
     assistant rows written since the last one it sent for that chat and sends a `message` event each.
   - `message.created` → `message` (cards, muted notices, background replies).
   - `approval.requested` / `approval.decided` → approval events.
   - `conversation.state_changed` → `conversation`.
   - On server ready: a snapshot of the 100 most recent conversations (title + last message), so the
     feed is filled immediately and heals after restarts. Event ids are message/approval ids, so the
     snapshot and retries are idempotent on the server.
   - Handlers only enqueue (background subscriptions, never slow a turn). One sender task batches,
     POSTs `{LUNA_GATEWAY_URL}/api/agent/chats/events` with `LUNA_GATEWAY_TOKEN`, backs off on errors,
     drops the batch on 401, and keeps a bounded queue. Without the gateway env (self-hosted Luna) it
     does nothing.
   - Reads Luna's own `conversations` / `messages` tables with plain SQL through
     `ctx.db_session_factory`; imports `luna_sdk` only.
3. **Previews:** a 200-character preview, on by default, off per Luna with `agents.chat_previews`
   (the server drops text when off).

## Rollout

1. Tests: plugin unit tests (fake bus, fake DB, fake HTTP), server suite, and a local end-to-end
   (plugin → local luna-service → `/api/feed` + stream).
2. Merge PR 2; luna-service deploys with migration 0022.
3. Commit the plugin to luna-marketplaces `main`; deploy the marketplace service at that commit
   (Render `srv-d8m7nct8nd3s73dofrm0`); verify the index entry and artifact sha256.
4. Pin `luna-service-mobile` in the admin image defaults and `plugin-set.toml`; rebake the current
   Luna version (`POST /api/admin/images/rebake`, `{base}-rN`), since Luna itself doesn't change.
5. Canary on one of roy's agents: feed fills, stream fires on a message, working shows during a turn.
6. `rollout_image.py promote-preserve` to every machine (old image kept for rollback);
   `rollout_image.py verify`.
7. App build against the live feed on roy's phone.

## Risks

- A plugin bug must never break a turn: every handler and the sender swallow and log.
- Event volume: one small POST per turn per Luna, batched; the ingest has no daily cap to hit.
- Telegram/WhatsApp chats are not Luna conversations and stay out of the feed.
- Deleted conversations: Luna emits no delete event; the app hides chats Luna no longer lists.
- Rollback: the previous image stays built and non-main; migrate machines back to it.

## Acceptance

- Every running machine reports the new image; its plugin list includes `luna-service-mobile`.
- A message on the web shows in `/api/feed` and on the phone within about a second, with preview,
  unread count, and "working…" while Luna replies. Approvals show as pending until decided.
- luna-service suite green; plugin tests green; no increase in tenant DB connections.
