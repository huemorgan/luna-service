# 060 — execution summary

## What was accomplished

### luna-service (commit `de201a3` on main → Render)
- **Fix 3 — token rotation ordering** (`cloud/provisioning/workflow.py`):
  `_provision_core` (fresh provision AND recreate) now mints the gateway
  token with `revoke_existing=False`, revokes old tokens only **after**
  `runtime.provision()` succeeds, and on failure revokes the undelivered new
  token while keeping the live one. This closes the recreate-path
  "Invalid tenant token" 401 storm (46+8 events/wk) that survived the Jul 22
  env-delta fix.
- **Fix 3b — admin rotate-token route**
  (`cloud/api/gateway_admin_routes.py::issue_agent_token`): default flipped to
  `revoke_existing=False`; explicit `?revoke_existing=true` for compromise
  response. Response note explains the env-push flow is the safe rotation.
- Tests: `cloud/tests/test_token_rotation_060.py` (4 tests — route default /
  explicit revoke, `_provision_core` success + failure ordering with a stubbed
  runtime). Full suite: **729 passed, 9 skipped**.
- `cloud/.luna-version` → 0.48.006, `luna` submodule → `bb1db25`.

### luna core (see `luna/plans/058-luna-service-prod-error-fixes/`)
Fixes 1 (DB TLS), 2 (cancel-safe chat cleanup), 5 (quiet 402), 4 (embed
timeout default 2.5 s) shipped as **0.48.006**; built from the admin Images
panel and rolled to the fleet (Set Main + Migrate All).

### Deliberate non-changes
- **No `?sslmode=require` appended to the composed agent DSN**
  (`_host_for_runtime`): pre-0.48.006 images pass URL query params to
  asyncpg as connect kwargs → `TypeError`, so the defensive param would
  crash any machine still on an older image after an env push. The core-side
  host heuristic (non-local host → TLS) covers the injected DSN as-is.
- **No token env backfill needed**: revoked-token 401s only bite when a
  machine holds a stale token; machines migrated to 0.48.006 are re-provisioned
  through the fixed path and receive a fresh valid token.
- **No marketplace changes**: luna-marketplaces was the *source* of the TLS
  pattern (already correct); nothing in this plan touches it.
- **#9 `trigger_list bad signature` (34/wk)**: root cause traced to Fix 1 —
  plugin-scheduler keeps its HMAC secret in the vault; vault reads failed with
  `SSL/TLS required`, so the plugin signed with a missing/stale secret. No
  scheduler-side fix; verify the cluster disappears post-rollout.
- **#7 wiki/goalseek `prompt_sections_slow`** and **#8 Render-API 401 tool
  errors** remain backlog per the plan (perf warnings / user misconfig, not
  failures).

## What we discovered along the way

- The Luna deploy lineage moved: `main` is the deploy branch again (0.48.005
  was promoted to all 37 machines by luna plan 057); the old
  `luna-service-deploy` branch is dead. `cloud/.luna-version` had drifted to
  0.38.003 — the 057 deploys bypassed it. Re-synced to 0.48.006 here.
- `revoke_other_tokens`/`revoke_raw_token` already existed (built for the
  env-delta fix `4278932`) — Fix 3 was wiring them into the two remaining
  callers, not new machinery.

## Production verification (2026-07-24, post-rollout)

- **Fleet**: all **37/37** machines on `registry.fly.io/luna-agents:0.48.006`
  (verified via `/api/admin/machines`).
- **Error feed** (`/api/admin/errors`), after the migration window:
  - Zero `SSL/TLS required` — Fix 1 confirmed.
  - Zero `Invalid tenant token` 401s — Fix 3 confirmed.
  - Zero `run_turn.error` / `muted.turn_failed` tracebacks for billing gates;
    replaced by the new clean `run_turn.billing_blocked` /
    `muted.turn_billing_blocked` warnings — Fix 5 confirmed live.
  - `memory.embed_timeout` now logs `timeout_s=2.5` (one hit right after the
    DB recovery, vs ~80-100/wk at 0.8 s) — Fix 4 confirmed live.
- **Migration side-effect (transient, self-healed)**: rebooting all 37
  machines at once briefly knocked the shared tenant Postgres into recovery
  mode (~20:48–20:54 UTC): a 6-minute storm of `database system is in
  recovery mode` / `connection was closed` warnings from plugin on_load and
  TTL sweeps. Cleared on its own; no errors after 20:57. Future fleet-wide
  migrations should be staggered.
- **Live turn**: chat turn against `vaselin-gamer` (0.48.006) — agent
  responded normally, memory write persisted over the TLS DB connection.

## Things to consider in the future

- The admin UI "rotate token" button now issues without revoking; if a true
  kill-switch UX is wanted, add a separate "revoke all" control that hits
  `?revoke_existing=true`.
- Once the whole fleet is ≥0.48.006, `_host_for_runtime` could append an
  explicit `sslmode=require` safely (belt and braces).
- Plan 059 (sleeping vs stopped states) still owns `agent_wake_failed` and
  most of the `proxy_502` noise.
