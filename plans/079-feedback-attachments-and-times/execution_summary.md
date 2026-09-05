# 079 — Execution summary

Shipped in 80f54f6, live on Render 2026-09-05 13:03Z (deploy verified via API).

## What landed

- **Attachments as meta fields.** Agent create_ticket accepts `transcript`
  (clamp 60k) and `agent_context` (clamp 200k) as payload fields, stored in
  the opening FeedbackMessage.meta (JSONB, no migration). The body stays the
  owner's words.
- **Elide-by-default agent read.** GET /tickets/{id} replaces attachment
  strings >4k with `{elided, chars, note}` unless `?include_attachments=1` —
  full text stays available with the same gateway key.
- **Reads are not updates.** Agent mark_read now uses a Core UPDATE pinning
  `updated_at` (same trick the admin read used), so opening a ticket never
  bumps it.
- **last_activity_at** = max(created, last admin reply, last client reply) in
  both agent `_ticket_summary` (plus `last_client_reply_at`) and admin
  `_ticket_row`.
- **Admin UI.** List column Updated → Last activity; drawer header shows
  Opened + last reply ago; each message shows ago + absolute datetime;
  transcript/agent_context render as collapsed details blocks.

## Verification

- 18 feedback-suite tests pass (5 new in test_079_feedback_attachments.py).
  Pre-existing cross-test pollution in test_078 (fails after test_feedback.py
  on a clean tree too) noted, unrelated.
- Production (via plugin-feedback 0.9.0 on vaselin-error-log-tracker):
  filed ticket eb5595f3 — body stayed one line, agent_context arrived as a
  10,023-char meta string with include_attachments=1, last_activity_at
  present in agent + admin APIs, two reads left updated_at byte-identical.
  Test ticket closed via admin status route.

## Ship order

Service first, then plugin-feedback 0.9.0 (plan 004) — old plugin + new
service unchanged; the reverse would have dropped attachments silently.
