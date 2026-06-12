# 01 — Signed delivery, end to end

The happy path: Composio fires an event, the relay verifies, resolves the
tenant, and the agent machine receives a correctly re-signed POST.

## Setup

- Local stack up; at least one running local agent (e.g. `alice-my-luna`).
- Control plane env has `CLOUD_COMPOSIO_WEBHOOK_SECRET=test-composio-secret`.
- A `composio_account_links` row maps `ca_dojo_alice_001` → alice's agent
  (create via admin API if absent).

## Steps

1. Run `python dev/sign_composio_event.py --secret test-composio-secret
   --connected-account ca_dojo_alice_001 --url
   http://localhost:8100/api/webhooks/composio`.
2. Confirm the script reports HTTP 202.
3. Within ~10 s, query `GET /api/admin/relay/deliveries` (as admin) or open
   the admin Webhook Relay page.
4. Check the agent container actually received the forwarded POST:
   `docker logs <agent-container> --since 2m` should show the request to
   `/api/p/plugin-connectors/events/composio` (status 200/202/404 acceptable —
   current Luna images don't verify yet; what matters is arrival).

## Pass

- Ingress returns 202.
- Delivery row goes pending → delivered with the agent's slug, attempts ≥ 1,
  a recorded status code, and a `delivered_at`.
- Agent container log shows the inbound events request.

## Fail

- 4xx/5xx from ingress, row stuck pending with no attempts, row dead on a
  reachable machine, or nothing in the container log.
