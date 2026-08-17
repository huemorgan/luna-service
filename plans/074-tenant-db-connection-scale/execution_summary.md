# 074 — execution summary (2026-08-17)

## Phase A — executed
- `idle_session_timeout` 15min → 5min in `ROLE_SETTINGS`
  (`cloud/db/tenant_provisioner.py`) and applied live to all 77 `luna_a_%`
  roles via `scripts/tenant_role_settings.py`. rolconfig verified.
- Pool sizes left at 2/3 (rationale in PLAN.md §Phase A.2).
- luna 0.82.005 (engine dispose on shutdown) built; rollout tracked in 073.
- Test `test_tenant_role_settings_073.py` updated for 5min — 3 pass.

## Phase B — PgBouncer: planned only
Not executed. Trigger: `tenant_db_saturation` alert or fleet > 60 machines.
Hosting decision recorded in PLAN.md: Fly app `luna-pgbouncer` (sjc, 2
machines, `luna-pgbouncer.internal:6432`), CP-rendered userlist.

## Also in this change set
- `LUNA_ATTACHMENT_MAX_MB=50` added to image default env
  (`PUT /api/admin/defaults`) and backfilled to the fleet with
  `POST /api/admin/machines/env/backfill?keys=LUNA_ATTACHMENT_MAX_MB`
  (in-place restart per machine; stopped machines restored afterwards).
