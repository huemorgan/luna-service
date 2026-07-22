# 053 — Error-log bug fixes (from 051 error-tracking corpus)

## Context

Plan 051's error tracking surfaced 407 prod events (Jul 21–22). Validation
against latest code (2026-07-22) confirmed four actionable defects:

1. **DB connection leak — 41% of all events.** `_plugin_disabled_guard` in
   `luna/plugins/plugin_api/app.py` is registered with `@app.middleware("http")`
   = starlette `BaseHTTPMiddleware`. Its anyio cancel scope cancels the request
   coroutine at arbitrary await points on client disconnect (SSE chat), killing
   pooled asyncpg connections mid-checkin → "Exception terminating connection"
   (110 ERROR) + "GC cleaning non-checked-in connection" (59 WARNING).
   `luna/timing.py` was already written pure-ASGI to avoid exactly this.
2. **Embed input > 8192 tokens never truncated.** `plugin_memory` sends raw
   text to the embed provider; oversized facts fail the real embed, get
   hash-embedding fallback on write, and become unfindable by real-vector
   recall.
3. **Scheduler "bad signature" storm has a written-but-unshipped fix.**
   plugin-scheduler 0.3.3 (self-repair: rotate-connect + retry on 401/403
   "bad signature", plus on-load credential validation) sits uncommitted in
   `luna-scheduler/plugin-scheduler`; marketplace serves 0.3.2.
4. **`goal_get` loose schema.** `goal_id` is a bare `{"type":"string"}` with no
   description — model passed a goal sentence as the id (validation error in
   prod).

## Goals

- Stop the connection-leak error class at the source (pure-ASGI guard).
- Truncate embed inputs so oversized facts get real (prefix) embeddings.
- Ship plugin-scheduler 0.3.3 to the official marketplace.
- Ship plugin-goalseek 2.2.2 with a described `goal_id` parameter.
- Roll the luna core fixes to the fleet (canary first), upgrade fleet plugins.

## Non-Goals

- Tuning `LUNA_EMBED_TIMEOUT_S` (intentional design, d326ade; discuss separately).
- Credit-exhaustion tenants (kateni-mellon, roniak-rocky, alexpe-my-luna) — billing, not code.
- prompt_sections_slow latency work (plan 045/046 territory).

## Approach

### A. luna core (repo `luna`, main; fleet target)

1. Rewrite `_plugin_disabled_guard` as a pure-ASGI middleware class (same
   403 JSON contract for `/api/p/{name}/...` when the plugin is disabled;
   scope-type passthrough for non-http). Register with `app.add_middleware`.
   No other `@app.middleware`/`BaseHTTPMiddleware` uses exist (verified).
2. `plugin_memory`: clamp text in `_embed_real` to `LUNA_EMBED_MAX_CHARS`
   (default 20000 ≈ well under 8192 tokens) before calling the provider.
   Applies to both write and recall paths (both go through `_embed_real`).
3. Bump `__version__` → 0.43.001, run the relevant test files, commit, push.

Note: main is already at 0.43.000 (SYSTEM_BASE rewrite, unshipped — fleet runs
0.42.013). The image roll therefore ships 0.43.000+fixes. Mitigation: test
agent + canary before migrate-all.

### B. plugin-scheduler 0.3.3 (repo `luna-scheduler/plugin-scheduler`)

Uncommitted working tree already contains the fix (client self-repair,
provision.repair, on-load validation, tests). Review diff, run tests, commit,
push, bump outer `luna-scheduler` submodule pointer, package
(`luna-plugins/scripts/package_plugin.py`), publish to marketplace `official`
via `publish_plugin.sh` (token in `luna-plugins/.env`).

### C. plugin-goalseek 2.2.2 (repo `luna-plugins/plugins/plugin-goalseek`)

Add description to `goal_id` in the `goal_get` ToolDef ("the goal's UUID from
goal_list/goal_open — never the goal text"), bump 2.2.1 → 2.2.2 (pyproject,
luna-plugin.toml, manifest), commit, push, package, publish.

### D. Deploy

1. Verify luna-marketplaces nested `luna` submodule pins a pushed sha (build
   precondition; broke the 052 build).
2. `POST /api/admin/images/build?branch=main` → poll → test-agent →
   `set-main` → canary `vaselin-my-luna` via `update-image` → probe →
   `migrate-all`.
3. Post-migrate: check for the reconciler stuck-`stopped` race; if agents
   stuck, temp-allowlist CP DB and flip status (052 procedure).
4. Fleet plugin upgrades: per agent, `POST /a/{slug}/api/auth/proxy-login` →
   `POST /api/p/plugin-marketplace/upgrade-all` with the JWT.

## Risks

- Ships 0.43.000 SYSTEM_BASE rewrite with the fixes — canary gate before fleet.
- Pure-ASGI guard must not break the disabled-plugin dojo/tests — run
  plugin_api tests.
- `upgrade-all` upgrades every plugin with a newer marketplace version, not
  just these two — acceptable (that's the product's own "update all" button).
- Cloudflare 100s cap on migrate-all — 30 machines fit (verified in 052).

## Acceptance criteria

- No `@app.middleware("http")`/BaseHTTPMiddleware in the agent app; guard
  behavior unchanged (403 on disabled plugin routes).
- `_embed_real` never sends >LUNA_EMBED_MAX_CHARS chars.
- Marketplace `official` serves plugin-scheduler 0.3.3 and plugin-goalseek 2.2.2.
- Fleet on the new image, 32/32 running; canary agent healthy.
- Fleet agents report the new plugin versions after upgrade-all.

## Execution result (2026-07-22)

All four fixes shipped and deployed.

- **luna core 0.43.001** (`1867c5e`): pure-ASGI `PluginDisabledGuard` (unit
  smoke: 403 disabled / 200 enabled / 200 non-plugin paths) + embed clamp
  `LUNA_EMBED_MAX_CHARS=20000` with `memory.embed_truncated` log. Relevant
  test suites pass; the 2 failures in 005.923 openapi-snapshot tests are
  pre-existing on clean HEAD (stale route snapshot).
- **plugin-scheduler 0.3.3** (`70f7371`, submodule bump `8421f02`): the
  uncommitted self-repair work was reviewed, tested (47 passed), committed,
  packaged, published to marketplace `official`.
- **plugin-goalseek 2.2.2** (luna-plugins `161927a`): all four bare `goal_id`
  params described; 512 tests passed; published to `official`.
- **Fleet roll**: image c2dfe857 built from main, test-agent healthy, set-main,
  canary vaselin-my-luna healthy, migrate-all 31 updated / 0 errors.
  Reconciler race hit again (5 agents stuck `stopped`:
  matanla-rico, vaselin-starla, kerenko-keren-s-assistant, matanla-messi,
  noamac-my-luna) — fixed via temp CP-DB allowlist UPDATE, reverted, stable
  through a sweep. Final: 33/33 machines on 0.43.001, all running.
- **Fleet plugin upgrades**: per-agent proxy-login → upgrade-all. Cross-account
  agents needed per-account minted cookies (proxy membership check); cold
  machines needed a wake GET before proxy-login (proxy-login POST does not
  wake). daniel-b-my-luna + kateni-mellon machines were dead (app not
  listening, predating the roll) — Fly restart fixed both. plugin-scheduler
  0.3.3 + plugin-goalseek 2.2.2 (+ pending curiosity/feedback/monday/render/
  whatsapp bumps) now on all 30 real agents. Skipped: 3 stale vaselin-test-*
  agents.

Follow-ups: re-run `scripts/pull-errors.py` after ~24h to confirm the leak
fingerprints (f984fc32…, eb4fad20…) and scheduler storm (f50610…) are gone;
reconciler race itself still needs a code fix (separate plan).

## Verification

- luna core: pytest for plugin_api + plugin_memory test files.
- plugin-scheduler: its pytest suite (includes new self-repair tests).
- Prod: test-agent health, canary probe, `/api/admin/machines` counters.
- Next-day `scripts/pull-errors.py` run should show the leak fingerprints
  (f984fc32…, eb4fad20…) and scheduler storm (f50610…) gone or near-zero.
