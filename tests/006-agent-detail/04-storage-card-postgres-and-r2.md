# 04 — Storage Card

## Setup
- On `/dashboard/agents/{id}` for an active agent

## Steps
1. Read the "Storage" card
2. Verify each row

## Expected
- **Postgres schema**: `luna_user_<slug>` (or `agent.db_schema` if non-null)
- **Postgres host**: from `CLOUD_TENANT_DB_HOST` (e.g. `luna-tenant-prod...render.com`)
- **Volume**: `/workspace · 1 GB` (size we set at provision; if not tracked, show `/workspace · default`)
- **R2 prefix**: `tenant/<slug>/`
  - If R2 credentials are configured, show object count + total bytes (e.g. `0 B · 0 objects`)
  - If R2 not configured (current state), show `not yet in use`
- **Vault key**: `derived · ref <last 6 chars of vault_key_ref>` or `derived` if no ref yet

## Pass criteria
- All five rows populated, no nulls
- R2 row degrades gracefully when creds are missing

## Fail criteria
- Crashes when R2 credentials are missing
- Postgres schema shows account slug instead of `luna_user_*` (means we're showing the wrong field)
