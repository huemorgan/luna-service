# 03 — Agent learns about an admin reply and relays it

**Goal:** after an admin replies, the agent's `/updates` poll reports the
ticket unread, the agent loads the `feedback-tickets` skill, reads the thread
with `feedback_ticket_get`, and relays the reply in plain words.

## Steps

1. Ensure a ticket exists that the agent filed or knows (from scenario 01),
   still with `agent_read_at` older than the admin reply (i.e. the AGENT has
   not opened it via the pane — see the shared read-marker note in the plan).
2. As admin, reply to that ticket in `/admin/feedback`.
3. In the Luna chat, start a fresh turn (the plugin polls `/updates` at most
   every ~10 min; for the test, either wait or restart the machine / trigger a
   poll). Ask the owner-style question: "any update on my feedback?"
4. The agent should surface that the team replied, load
   `load_skill('feedback-tickets')`, then on the next turn call
   `feedback_ticket_get` and relay the team's message in plain words (not raw JSON).

## Pass / fail

- PASS: agent proactively (or on the "any update?" prompt) reports the team's
  reply, having read it via the API; `agent_read_at` advances so the note
  clears afterwards.
- FAIL: agent never learns of the reply; or pastes raw ticket JSON at the
  owner; or the `/updates` poll errors.

## Note

`/updates` is throttled to ~10 min in the plugin. To exercise this quickly,
you may call the control-plane endpoint directly with the tenant token
(`GET /proxy/api/agent/feedback/updates`) to confirm the server side reports
the unread ticket, then verify the agent-side relay separately.
