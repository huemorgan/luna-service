# 079 — Feedback attachments as fields + honest timestamps

Roy (2026-09-05): a pane-filed ticket with "attach context" ON arrives as one
massive opening message — transcript and full agent context are concatenated
into the body, so it reads as if the owner wrote a wall of text when they
wrote one line. Also, ticket list times show `updated_at`, which bumps when
the ticket is merely *opened* (agent `mark_read` fires the onupdate hook), so
"just now" means "someone read it", which is useless.

## Changes (service side — plugin-feedback 0.9.0 is the sibling)

1. **Attachments are fields, not body text.** Agent create endpoint accepts
   two new optional string fields, stored in the opening `FeedbackMessage.meta`
   (JSONB — no migration) next to the existing `conversation_excerpt` /
   `technical`:
   - `transcript` — rendered conversation history (clamped 60k chars)
   - `agent_context` — full agent context text (clamped 200k chars)
   The ticket shape is then: title / user message (body) / agent context /
   conversation history — each its own thing.

2. **Agent API exposure (the key requirement).** `GET /tickets/{id}` returns
   meta as stored, except strings in these two keys longer than 4k chars are
   elided to `{"chars": N, "elided": true, "note": …}` unless
   `?include_attachments=1` — a woken agent reading a ticket must not swallow
   200k chars unasked, but the full text stays one call away with the same
   gateway key.

3. **Read is not an update.** Agent `mark_read` now writes `agent_read_at`
   with the explicit `updated_at=updated_at` UPDATE (same trick the admin read
   already uses) so opening a ticket never bumps "Updated".

4. **`last_activity_at`** (max of created_at / last_admin_reply_at /
   last_client_reply_at) added to both the agent `_ticket_summary` (plus
   `last_client_reply_at`) and the admin `_ticket_row` — the honest "last
   change" time for list rows.

5. **Admin UI (FeedbackPage.tsx):**
   - list "Updated" column → `last_activity_at`
   - drawer header: `Opened Xd ago · last reply Yd ago` (reply line only when
     the thread has replies)
   - every message: time-ago **and** absolute datetime
   - `meta.transcript` / `meta.agent_context` render as collapsed
     `<details>` blocks with char counts — side notes, never body text

## Compat

Old plugin + new service: unchanged (old plugin never sends the new fields —
it still appends to body). New plugin + old service: new fields ignored →
context lost; ship order is service first, plugin second.

## Tests

Extend cloud/tests: attachments stored in meta; elided by default on agent
get; full with include_attachments=1; mark_read leaves updated_at unchanged;
last_activity_at present and correct.
