# Plan 078 — execution summary

Date: 2026-09-05. Master plan: luna repo `plans/106-validated-bugfix-batch/PLAN.md` (phases 7a/7b).

## What shipped

Commit `1682f26` ("078: zombie scheduled work + feedback ticket idempotency").

### 7a — zombie scheduled work after agent teardown

- `cloud/billing/hosting.py`: `_handle_agent_teardown` now revokes all unrevoked
  `GatewayTenantToken` rows for the agent and best-effort disconnects the agent's
  scheduler account (`scheduler_svc.provision.disconnect_agent`); a disconnect
  failure logs a warning and never blocks teardown.
- `cloud/api/scheduler_routes.py`: `scheduler_fire_relay` agent lookup filters
  `Agent.deleted_at.is_(None)` — fires for a tombstoned slug get 404 instead of
  relaying to a dead agent.
- `cloud/scheduler_svc/sweep.py` (new): `sweep_once()` lists scheduler accounts
  via `GET /stats`, deletes accounts whose slug has no live agent
  (`DELETE /accounts/{slug}`); `sweep_loop()` runs every 6h and never dies.
- `cloud/runtime/exclusive.py`: `LOCK_SCHEDULER_SWEEP = 0x1004A_05`.
- `cloud/main.py`: lifespan spawns the sweep under the advisory lock, gated by
  `CLOUD_SCHEDULER_SWEEP=1` (default on); cancelled on shutdown.

### 7b — feedback ticket idempotency (server half)

- `cloud/db/models.py`: `FeedbackTicket.client_ref` (Text, nullable) + unique
  index `ux_feedback_tickets_client_ref`.
- `cloud/alembic/versions/0019_feedback_client_ref.py`: migration.
- `cloud/api/feedback_agent_routes.py`: `create_ticket` pre-checks an existing
  ticket by `client_ref` before rate limiting and returns 200
  `{id, status, created_at, duplicate: true}`; race window covered by
  IntegrityError → rollback → re-read → duplicate response.
- Client half: plugin-feedback 0.7.0 (its plan 002) sends `client_ref`.

## Verification

- `cloud/tests/test_078_zombie_and_idempotency.py`: 8/8 pass.
- Full suite: 831 passed, 9 skipped, 1 pre-existing failure
  (`test_billing_stripe_clawback::test_refund_of_spent_credits_creates_debt_repaid_by_next_grant`,
  fails on a clean tree too).
- Deploy: push of this repo's main triggers the Render deploy; migration 0019
  runs on release. See rollout status in the luna repo
  `plans/106-validated-bugfix-batch/execution_summary.md` (phase 8).
