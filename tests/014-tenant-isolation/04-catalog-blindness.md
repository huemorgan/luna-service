# 04 — Catalog blindness

Run from inside tenant machine A, connected to A's own DB.

## Steps
1. `psql "$LUNA_DATABASE_URL" -c "SELECT datname FROM pg_database;"`
2. `psql "$LUNA_DATABASE_URL" -c "\dn"`  (schemas)
3. `psql "$LUNA_DATABASE_URL" -c "SELECT schemaname, tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');"`

## Pass
- Step 1: database *names* are visible (acceptable residual) — but A cannot connect to them (see 02/03).
- Steps 2–3: only A's own schema(s) and tables appear. No `luna_user_*` of other tenants, no other tenant data.

## Fail
- Any other tenant's tables/schemas listed with their contents reachable.
