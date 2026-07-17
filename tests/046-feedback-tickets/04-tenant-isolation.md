# 04 — Tenant isolation + admin triage

**Goal:** an agent can only see its own tickets; cross-agent ids return 404
(not 403, so existence isn't leaked); admin filters work.

## API-level (tenant token)

1. Agent A files a ticket (note its id).
2. Using Agent B's tenant token, `GET /proxy/api/agent/feedback/tickets/{A_id}`
   → **404**.
3. `GET /proxy/api/agent/feedback/tickets` with Agent B's token does NOT list
   Agent A's ticket.
4. No/invalid token → 401.
5. Fire >30 creates in a day with one token → later creates return **429**.

## Admin triage

6. `/admin/feedback` lists tickets across all agents, unanswered-first.
7. Filters by status / category / origin / agent narrow the list.
8. Closing a ticket sets status = closed; a subsequent client reply reopens it
   (status → open).

## Pass / fail

- PASS: isolation holds (404 cross-agent, no leakage in list), rate limit
  triggers, admin filters and status controls behave.
- FAIL: any cross-agent read/list leak; 403 instead of 404; no rate limit;
  admin filters broken.
