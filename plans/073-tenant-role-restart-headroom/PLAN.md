# 073 — tenant DB roles: headroom for restart overlap

## Problem
2026-08-17: `TooManyConnectionsError: too many connections for role
"luna_a_vaselin_linearascent_promote"` twice, each within minutes of a
control-plane-driven machine restart (`update-image`, then `env/backfill`).
Plan 071 capped every tenant role at `CONNECTION LIMIT 6` (pool 2 + overflow
3, plus a little). Diagnosis via `pg_stat_activity` on luna-tenant-prod:

- A Fly restart halts the VM; the old process's pooled backends get no FIN
  and stay open server-side. The cluster's TCP keepalive is
  300 s + 60 s × 5 (≈10 min); the role's `idle_session_timeout` is 15 min.
- The new process opens its own pool → old + new > 6 while the orphans age
  out. Any turn + scheduled trigger + attachment summary in that window fails.

## Changes
- `cloud/db/tenant_provisioner.py`: `ROLE_CONNECTION_LIMIT = 12` (fits two
  pools) and `ROLE_SETTINGS` adds `tcp_keepalives_idle=30`,
  `tcp_keepalives_interval=10`, `tcp_keepalives_count=3` (server reaps a dead
  peer in ~60 s). Both applied through `role_settings_sql(role)` on create and
  on every re-provision.
- `scripts/tenant_role_settings.py`: idempotent sweep over all existing
  `luna_a_%` roles (`--dry-run` supported).
- Tests: `cloud/tests/test_tenant_role_settings_073.py`.
- Companion: luna plan 079 (0.82.005) disposes the SQLAlchemy engine on
  shutdown so graceful stops close their connections outright.

## Rollout
1. Apply the role settings live to all roles (done first — the fleet-wide
   `LUNA_ATTACHMENT_MAX_MB` backfill was mid-flight and restarting machines).
2. Commit + push; Render deploy.
3. Build image 0.82.005, set main, `update-image` on the 0.82.x machines,
   restore stopped state.
4. Verify: `pg_roles.rolconnlimit = 12` + keepalive GUCs on the roles; no
   `TooManyConnectionsError` in tenant logs across the remaining restarts.

## Budget note
37 machines × 12 = 444 nominal > `max_connections` 103, same as before with
6 (222); the limit is a per-tenant blast-radius cap, not a fleet budget. Real
usage stays ~1–4 per role; the `tenant_db_saturation` alert (071) still
watches the total.
