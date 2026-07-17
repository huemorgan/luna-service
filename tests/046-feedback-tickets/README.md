# tests/046-feedback-tickets

Dojo-style E2E scenarios for the feedback-ticket feature (plan 046).

You (the LLM) are the test runner: open a real browser, drive a real hosted
Luna + the luna-service admin UI, and judge each scenario with your own eyes
(screenshots + DOM). No `expect()` — you read the page and decide pass/fail.

## Environment

- Control plane (luna-service): local `uvicorn cloud.main:app` on `:8100`,
  backed by the local Postgres from `dev/cloud/docker-compose.yml` (port 5435).
  Migration `0011_feedback_tickets` must be applied.
- A hosted-style Luna running locally with **plugin-feedback** installed and
  `LUNA_GATEWAY_URL` / `LUNA_GATEWAY_TOKEN` (or the
  `LUNA_FEEDBACK_SERVICE_URL` / `LUNA_FEEDBACK_TOKEN` overrides) pointing at the
  local control plane and a valid tenant token for the test agent.
- Admin session: signed in as an `is_admin` user on the control plane.

## Scenarios

1. `01-agent-files-feedback.md` — the agent files a ticket on its own
   (`written_by="agent"`) with no explicit owner request, from indirect
   frustration; it lands in the admin Feedback page.
2. `02-owner-pane-and-thread.md` — owner writes a ticket in the Feedback pane,
   admin replies, owner sees the reply threaded.
3. `03-agent-learns-reply.md` — after an admin reply, the agent's unread poll
   surfaces it and the agent relays it to the owner.
4. `04-tenant-isolation.md` — one agent cannot read another agent's ticket
   (404, not 403); admin filters/triage work.
