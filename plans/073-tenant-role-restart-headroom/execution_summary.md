# 073 — execution summary (2026-08-17)

## Trigger
`asyncpg.exceptions.TooManyConnectionsError: too many connections for role
"luna_a_vaselin_linearascent_promote"` after an in-place machine restart
(the 072 env backfill). Root cause: the halted VM's pooled backends stayed
open on Render (server keepalive 300 s + 60 s × 5 probes ≈ 10 min, idle
timeout 15 min) while the new process opened its own pool → 6+ > CONNECTION
LIMIT 6.

## Done
- `cloud/db/tenant_provisioner.py`: `ROLE_CONNECTION_LIMIT = 12`,
  `ROLE_SETTINGS` (idle_session_timeout / idle_in_transaction 5min,
  tcp_keepalives 30/10/3), `role_settings_sql()`; CREATE ROLE and the
  settings loop use them.
- `scripts/tenant_role_settings.py`: rewritten to plain asyncpg
  (`ssl="require"`), `--dry-run`, applies `role_settings_sql` to every
  `luna_a_%` role. (SQLAlchemy asyncpg engine to Render hangs from a laptop.)
- Tests `cloud/tests/test_tenant_role_settings_073.py` — 3 pass.
- Live: all 77 tenant roles now `rolconnlimit=12`, rolconfig
  `idle_session_timeout=5min, idle_in_transaction_session_timeout=5min,
  tcp_keepalives_idle=30, tcp_keepalives_interval=10, tcp_keepalives_count=3`.
  Orphans of a dead VM are now dropped in ≤60 s; idle pool slots in 5 min.
- luna 079 (0.82.005): `dispose_engine()` on app shutdown, so a graceful
  restart releases its pool before the VM halts. Image
  `5fd5aa8b-2886-4e3a-9cba-e0d52c926e46` built.
- Commits `660f881` (+ this follow-up), Render deploy `dep-da1m0ie417fc73emnk2g`.

## Verified
`SELECT usename,count(*) FROM pg_stat_activity` — 28 backends / 37 machines
after the settings; no role above 4. Re-provisioning path exercised by tests
only (no new tenant created).
