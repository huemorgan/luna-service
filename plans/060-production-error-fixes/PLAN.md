# 060 — Production error triage & fixes (7-day error pull)

Root-cause fixes for the production errors surfaced by `scripts/pull-errors.py`
(pulled 2026-07-24, 168h window, 186 groups). Each fix is assigned to its
**owning repo** — luna-service, luna core (submodule), a plugin, or config/env.

`agent_wake_failed` ("Machine no longer exists") is **out of scope here** — it
has its own design in **plan 059** (sleeping vs stopped states).

## Full error inventory (by disposition)

### Real bugs (fix)
| # | Signal | Count | Owner | Root cause |
|---|--------|-------|-------|-----------|
| 1 | **`SSL/TLS required`** — plugin `on_load` (wiki/playbooks/scheduler/mcp/curiosity), `vault read failed`, `approval.ttl_sweep_failed`, `approval.audit_write_failed` | ~200 combined | **luna core** | Shared DB engine connects to Render Postgres with no TLS |
| 2 | **asyncpg leak** — "Exception terminating connection", "garbage collector … non-checked-in connection" | 127 + 68 | **luna core** | Pooled connection close interrupted by request/task cancel |
| 3 | **`gateway_auth` "Invalid tenant token"** (anthropic/openai) | 46 + 8 | **luna-service** | Machine presenting a revoked `lsv1-` after recreate/rotate (revoke-before-push) |
| 4 | **`memory.embed_timeout` / `recall_degraded_empty`** | 81 + 107 | **config + luna core** | 0.8s embed timeout too tight for gateway RTT → recall silently empties |
| 5 | **`run_turn.error` / `muted.turn_failed`** logged as ERROR+traceback | 8 + 16 | **luna core** | 402 billing-limit block surfaced as a crash log, not a clean "limit reached" |

### Mostly benign / noise (reduce, don't chase)
| # | Signal | Count | Owner | Disposition |
|---|--------|-------|-------|-------------|
| 6 | **`proxy_502` "Proxy stream broke (RemoteProtocolError)"** | ~120 | luna-service | Upstream (Fly/agent) closed SSE mid-stream — machine restart/sleep. Largely resolved by **plan 059**; otherwise quieter fingerprinting. Not a timeout bug. |
| 7 | **`plugin.prompt_sections_slow`** (wiki 6473ms, goalseek 2651ms) | ~250 | plugins | Perf warning; wiki/goalseek prompt-section build slow. Backlog perf. |
| 8 | **`tool.error 401 Unauthorized` api.render.com/v1/services** | ~10 | plugin/tool | A tool calls the Render API with bad/missing auth — investigate which tool; likely a user/agent misconfig. |
| 9 | **`trigger_list error: bad signature`** | 34 | luna-service / scheduler | Scheduler HMAC secret mismatch (rotation) — may share cause with #3 token rotation. Verify. |
| 10 | **`context.gauge_divergence`** | ~28 | luna core | Token-estimate vs provider-count telemetry; not a failure. Leave. |
| 11 | **`condense.pass_failed`** | ~6 | luna core | Likely collateral of #1 (DB) or a model error — recheck after #1 ships. |
| 12 | **`tool.error` goal_get not found / cold first-contact budget** | ~19 | — | Expected guardrails / user error. No action. |

## Fixes

### Fix 1 — DB connections use TLS (luna core) — **P0, unblocks the most**
**Root cause** ([research](ca9c47a5-3262-42cd-af0a-7a85dbd64f1f)):
`luna/luna/data/__init__.py` `get_engine()` builds the one async engine used by
vault, approvals, and every plugin's `on_load`, with **no** `connect_args`.
luna-service injects `LUNA_DATABASE_URL` pointing at
`*.oregon-postgres.render.com` (`cloud/provisioning/workflow.py:_host_for_runtime`),
which **requires** SSL. So the first query each plugin/vault/approval makes gets
`SSL/TLS required`.

**Critical detail:** appending `?sslmode=require` does **not** fix
SQLAlchemy+asyncpg (it's passed as a kwarg → `TypeError`). The proven pattern is
`connect_args={"ssl": ssl_context}` — already used in
`luna-marketplaces/service/app/database.py:29-36`.

**Change (luna core `luna/data/__init__.py`):** when the DSN host looks hosted
(Render host or `LUNA_ENV=production`), pass
`connect_args={"ssl": ssl_ctx}` on both the pooled and NullPool engines. Mirror
marketplaces. Strip/ignore any stray `sslmode` query param.

**Defensive (luna-service):** in `_compose_agent_db_url` / `_host_for_runtime`,
guarantee the injected DSN is SSL-capable for `fly-machines` (don't rely on
`sslmode=` alone). Backfill the env on live machines after the core image ships.

**Verify first:** read one live machine's `LUNA_DATABASE_URL` (admin → Machines
→ Env) to confirm whether `sslmode`/`ssl` is present. This decides whether the
core fix alone is enough.

**Owner:** luna core (primary) + luna-service (defensive). Needs a Luna image
build + fleet rollout.

### Fix 2 — cancel-safe DB session close (luna core) — **P1**
**Root cause:** SSE chat stream opens short DB sessions; on client
disconnect/hard-stop the pool's connection terminate runs inside a cancelled
greenlet → `CancelledError`, connection never returned → GC warning. The chat
handler also does *more* DB work in the `except CancelledError` and `finally`
blocks (`plugins/plugin_api/app.py`), widening the race.

**Change (luna core):** after `CancelledError`/`GeneratorExit`, do **not** start
new DB work; close sessions in a shielded task that swallows cancel; ensure every
per-request session is a strict `async with` that can't outlive the request.
Consider `pool_reset_on_return` / explicit `session.close()` hygiene.

**Owner:** luna core. Ships with the same image as Fix 1.

### Fix 3 — don't revoke a live token before the new machine is healthy (luna-service) — **P1**
**Root cause** ([research](29e29b7e-fcde-4931-9691-66b9a517dcce)):
the env-delta race was fixed Jul 22 (commit `4278932`: push env → then
`revoke_other_tokens`). But **recreate** (`_provision_core` via
`_recreate_with_volume`) and the **admin "rotate token"** endpoint still mint
with `revoke_existing=True` (default), revoking the live token *before* the new
machine boots / env is pushed. Any in-flight or still-running process on the old
token then 401s → this critical.

**Change (luna-service):**
- `_provision_core` / recreate: adopt the env-delta ordering — provision with
  `revoke_existing=False`, wait for machine healthy + env pushed, **then**
  `revoke_other_tokens`; on failure keep the old token valid.
- `gateway_admin_routes.py` `issue_agent_token`: either push the new token to
  the machine env in the same call, or default to not revoking the live one.
- **Recovery:** env-backfill the currently-broken agents so they get a valid
  token now.

**Owner:** luna-service. Also check whether #9 `trigger_list bad signature` is
the same rotation problem (scheduler HMAC secret) and fix alongside.

### Fix 4 — embed timeout headroom (config + luna core) — **P2**
**Root cause:** `LUNA_EMBED_TIMEOUT_S` defaults to **0.8s**
(`plugins/plugin_memory`), which is routinely exceeded on the gateway round-trip;
a miss cools the provider 60s and makes recall return `[]` (degraded).

**Change:** raise `LUNA_EMBED_TIMEOUT_S` (e.g. 2.5–3s) via the agent image env
injected by luna-service; optionally revisit the cooldown-cascade behavior in
`plugin_memory` so one timeout doesn't blind recall for 60s.

**Owner:** config (luna-service image env) first; luna core only if policy change
wanted.

### Fix 5 — 402 billing block shouldn't log as a crash (luna core) — **P2**
**Root cause:** when the gateway returns `402 {code: luna_monthly_limit}`, the
agent raises `ModelHTTPError` and logs `run_turn.error` / `muted.turn_failed`
with a full traceback — noise that hides real crashes.

**Change (luna core):** catch the frozen 402 billing contract (`error.code` in
credits_exhausted / luna_daily_limit / luna_monthly_limit / …) in the run/muted
turn path and surface a clean "limit reached" outcome (info/warning, no
traceback). The 402 contract is already stable (`enforcement.py`).

**Owner:** luna core.

## Phasing
1. **luna core image** (Fixes 1, 2, 5 + embed default 4): one coordinated image
   build. Fix 1 is the big win. Verify a live DSN first.
2. **luna-service** (Fix 3 token ordering + recovery backfill; #9 HMAC check;
   #6 noise): independent deploy, no image needed.
3. **Rollout**: build Luna image, set Main, migrate fleet (same mechanism as the
   xai fix); env-backfill tokens + embed timeout.
4. **Verify in prod**: re-run `scripts/pull-errors.py` after rollout; SSL cluster
   → ~0, asyncpg leak down, no new invalid-token criticals, embed timeouts down.

## Cross-repo summary
| Fix | Repo | Ship vehicle |
|-----|------|--------------|
| 1 DB TLS | luna core (+ luna-service defensive) | Luna image + fleet |
| 2 session cancel | luna core | Luna image + fleet |
| 3 token revoke ordering | luna-service | Render deploy |
| 4 embed timeout | luna-service env (+ luna core opt) | env backfill |
| 5 402 not a crash log | luna core | Luna image + fleet |

## Risk
- Fix 1 touches the core DB engine for every agent — stage on one machine, then
  fleet. Low logical risk (adds TLS that the server already requires).
- Fix 3 must stay idempotent and never leave an agent with zero valid tokens.
- Uncertainty: exact prod `LUNA_DATABASE_URL` / `CLOUD_TENANT_DATABASE_URL`
  contents (verify live before choosing core-only vs core+service for Fix 1).
