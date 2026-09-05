# Plan 078 — zombie scheduled work + feedback ticket idempotency

Date: 2026-09-05. Sibling of luna repo `plans/103-validated-bugfix-batch/PLAN.md`
(phases 7a/7b) and plugin-feedback `plans/002-ticket-idempotency`.

## 7a — zombie-token scheduled work

### Evidence
- Error Tracking, 2026-08-31 → 09-04: daily `gateway_auth` "Invalid tenant token
  on gateway service 'X' (machine token revoked or unknown)" at hh:00:20 with a
  retry at hh:01:2x, on interleaved 3-hourly grids; 44→66→98→110→83 events/day;
  agent resolves to None. The openai grid joins 09-01 and doubles from 09-03,
  tracking the Devops-FF machine deletion on 09-03/09-04.
- Live probe 09-05: every surviving vaselin machine token returns 200 on the
  gateway; a bogus token returns 401 JSON. So the failing callers are machines
  that no longer exist in the control plane (deleted/re-provisioned) but still
  hold their old env token and still fire scheduled work.

### Root cause (validated in this repo)
- `_handle_agent_teardown` (cloud/billing/hosting.py) destroys the machine and
  volume, but never revokes the agent's `GatewayTenantToken` rows and never
  disconnects the agent's account on the external scheduler service
  (`cloud/scheduler_svc/provision.disconnect_agent` exists and has no caller in
  the teardown path).
- The public fire relay (`cloud/api/scheduler_routes.py:scheduler_fire_relay`)
  looks up the agent by slug with no `deleted_at` filter — a tombstoned agent
  whose machine survived teardown (destroy raced/failed, or the slug was
  re-provisioned) is still woken and fired.
- Nothing sweeps the scheduler service's accounts against live agents, so an
  account orphaned before this fix keeps firing forever.

### Date assumption
Events continue through 09-04 (latest dump) and none of the three code paths
above changed between 08-31 and HEAD ⇒ the gap is current.

### Fix
1. Teardown: revoke all unrevoked gateway tokens in the same transaction that
   tombstones runtime refs; best-effort `disconnect_agent` after commit.
2. Fire relay: filter `Agent.deleted_at IS NULL`; a tombstoned slug returns
   404 so the scheduler service dead-letters the trigger.
3. Sweep: `cloud/scheduler_svc/sweep.py` — periodically list the service's
   accounts (`/stats`) and DELETE any account whose slug has no live agent.
   Runs in the lifespan behind a new advisory lock (`LOCK_SCHEDULER_SWEEP`),
   env-gated `CLOUD_SCHEDULER_SWEEP=1`, every 6h with a first pass at boot.

Out of scope: stopping a still-running Fly machine that the control plane no
longer knows about (no record to act on; its LLM calls already fail 401 and
the sweep stops the service-side fires that wake it).

## 7b — feedback ticket idempotency (server side)

### Evidence
- 2026-08-31 tickets 011–015: five-ticket cancel cascade for one mis-send.
- 2026-09-01 tickets 005–007: truncation correction + addendum spawned new
  tickets. `create_ticket` (cloud/api/feedback_agent_routes.py) inserts
  unconditionally — no idempotency key anywhere.

### Fix
1. `feedback_tickets.client_ref` (nullable text, unique index — Postgres
   ignores NULLs, so history is unaffected). Migration 0019.
2. `create_ticket`: when the payload carries `client_ref`, return the existing
   ticket (200, `duplicate: true`) instead of inserting; on the insert race,
   catch the unique violation and re-read. plugin-feedback ≥0.7.0 sends the
   ref (uuid5 over sha256(host|title|body)).

## Ship
Part of luna 103 phase 8: deploy cloud (migration runs via
`python -m cloud.db.migrate` on deploy), then plugin pins + image rollout.
