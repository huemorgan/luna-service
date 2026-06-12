# 03 — Unroutable event

A validly signed event whose connected account maps to no agent must be
kept for visibility but never forwarded or broadcast.

## Steps

1. `python dev/sign_composio_event.py --secret test-composio-secret
   --connected-account ca_nobody_knows_me --url
   http://localhost:8100/api/webhooks/composio` → expect 202 (we accept the
   delivery so Composio doesn't retry forever; routing failure is ours).
2. Check `GET /api/admin/relay/deliveries` — newest row has
   status=unroutable, no agent, attempts=0.
3. Wait ~15 s (a forwarder cycle), confirm the row stays unroutable and no
   agent container log shows a forwarded request for this webhook-id.
4. Now create a link for `ca_nobody_knows_me` → alice via the admin links
   API, and send a NEW signed event with the same connected account.
5. New delivery routes and delivers (old unroutable row stays as history).

## Pass

- Unroutable rows are visible, never forwarded; after the link exists new
  events route normally.

## Fail

- Unroutable event forwarded anywhere, or new event still unroutable after
  the link was added.
