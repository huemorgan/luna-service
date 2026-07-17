# 01 — Agent files feedback on its own (no explicit owner request)

**Goal:** verify the agent itself files a ticket from indirect frustration
(`written_by="agent"`), the `feedback_ticket_send` approval card shows the payload,
and the ticket appears in the admin Feedback page with origin = "agent".

This is the primary "agent logs things without the user" scenario the user
called out.

## Preconditions

- Local Luna with plugin-feedback installed, connected to the local control
  plane (tenant token valid for the test agent).
- Admin signed in to the control plane in a second browser tab.

## Steps

1. In the Luna chat, provoke indirect frustration WITHOUT asking for feedback,
   e.g. type a couple of turns like:
   - "this keeps failing, this is useless"
   - "ugh forget it, nothing works"
2. Observe the agent's behavior. It should decide to file feedback itself
   (capability note primes it: indirect frustration → file with
   `written_by="agent"`).
3. A `feedback_ticket_send` approval card appears (policy = `prompt_always`).
   Read it: it should carry a summary, details, `written_by=agent`, and
   (likely) the conversation attached. Approve it.
4. The tool returns `{sent: true, ticket_id: …}` and the agent tells the owner
   it filed feedback.

## Admin verification

5. In the admin tab, go to `/admin/feedback`.
6. The new ticket is listed: origin badge = **agent-filed** (not owner),
   a category, status = **open**, the agent's name/slug, and a recent
   "updated" time.
7. Open the ticket. The thread shows one message authored by `agent`. The
   context panel shows agent slug + machine identity (server-enriched), and
   the conversation excerpt if attached.

## Pass / fail

- PASS: agent filed the ticket itself (no explicit "send feedback" from the
  user), it shows in `/admin/feedback` with origin=agent, and the thread +
  context render correctly.
- FAIL: agent only sympathized and filed nothing; or the ticket never reached
  admin; or origin shows as owner/user; or the approval card leaked a raw
  token/secret in the payload.
