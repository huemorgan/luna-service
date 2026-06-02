# Scenario 01 — Signup provisions a Luna

## Preconditions

- Fresh DB (`make cloud-reset`)
- No running `luna-*` containers (`docker ps -f name=luna-`)
- `luna-hosted:dev-001` image built locally

## Scenario

1. Open `http://localhost:8000/` in incognito
2. Click "Sign in with Google" (stub mode: pick Alice)
3. After OAuth completes, observe what URL we land on
4. Run `docker ps -f name=luna-` repeatedly during the next 30 seconds
5. Once a `luna-alice` container appears, watch its status until it becomes "healthy"
6. Observe the UI — what does it show during this time?

## Expected Behavior

- Lands on `/alice` (or `/dashboard` with auto-redirect to `/alice`)
- While provisioning: friendly "Setting up your Luna..." screen with spinner, optionally with progress text ("Creating database... Booting your Luna...")
- Within ~30 seconds: container `luna-alice` running and healthy
- UI transitions to the actual Luna chat interface
- DB:
  - `agents` table: 1 row, account_id=Alice's, status=`running`, runtime_kind=`docker-local`, runtime_ref=`luna-alice`, internal_url=`http://luna-alice:8000`, db_schema=`luna_user_alice`
  - In the tenant Postgres DB: schema `luna_user_alice` exists with Luna's tables
- A scoped Postgres role exists for Alice's schema (verify in `pg_roles`)

## Fail Conditions

- ❌ UI stays on a blank/error screen
- ❌ Container is created but never becomes healthy
- ❌ Agent row stuck in `provisioning` after 60s
- ❌ Schema created but role missing (or vice versa — partial state)
- ❌ Multiple containers created (`luna-alice-1`, `luna-alice-2` — race condition)
- ❌ Provisioning takes > 60s

## Verify

- Screenshot at: landing, provisioning screen, final chat UI
- `docker ps` output before, during, after
- DB rows: `SELECT * FROM agents WHERE account_id = (SELECT id FROM accounts WHERE slug='alice')`
- Tenant DB schema check: `SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'luna_user%'`
- Control plane logs show each provisioning step

## Notes

The big moment. This is what the whole MVP exists to do — signup → working Luna in under a minute. If this works, the platform works.
