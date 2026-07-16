# 042 — Wiki auth stability: stable per-agent JWT secret + pane token fix

> Kill the recurring `Error: GET /graph?wiki=main -> 401` in the Wiki pane
> (seen on Rayla and Starla) at both of its roots. No workarounds — the
> long fix, deployed end to end so the wiki resolves in production.

## Root cause (two independent bugs, both required for the 401 to persist)

1. **Ephemeral JWT secret on hosted machines.** `luna/luna/auth/jwt.py`
   `_jwt_secret()` reads `LUNA_JWT_SECRET` from env, else persists a random
   secret at `~/.luna/jwt_secret`. On Fly machines `HOME=/root` is ephemeral —
   only `/workspace` is a volume — and `cloud/runtime/fly_machines.py` never
   sets `LUNA_JWT_SECRET`. Every machine restart (autostop wake, deploy,
   env update) rotates the secret and invalidates every outstanding token.

2. **Wiki pane retries with the same stale token.** The pane
   (`luna-plugins/plugins/plugin-wiki/wiki-src/src/lib/auth.ts`) treats
   `localStorage['luna.token']` as a fallback. On luna.com.ai localStorage is
   origin-wide, so that key holds whatever agent's token wrote it last (the
   Shell namespaces its own key since 008.996; this un-namespaced one is
   legacy). On a 401, `invalidateToken()` clears only the in-memory token;
   the retry's `getTokenAsync()` immediately short-circuits on the same stale
   localStorage value instead of waiting for the Shell's fresh
   `{type:'luna-auth'}` postMessage. The server-side 035 cookie fallback
   (`luna/luna/auth/dependency.py:59`) can't help — the cloud proxy strips
   cookies before forwarding.

## Result

- New/reprovisioned machines get a **stable per-agent `LUNA_JWT_SECRET`**,
  derived HKDF-style from `CLOUD_TRUSTED_PROXY_SECRET` + agent id (same
  pattern as `derive_proxy_secret` / `derive_relay_secret`). Restarts no
  longer invalidate tokens.
- Existing fleet backfilled via the admin env-backfill endpoint (one
  in-place machine restart each).
- plugin-wiki **0.7.1**: when embedded in an iframe the pane uses ONLY the
  Shell postMessage token — the localStorage fallback remains solely for
  direct/dev opens. A 401 retry now waits for a fresh Shell token.
- Published to the marketplace and pushed to the existing agents
  (Rayla, PA, Starla) via the tenant `plugin-marketplace/upgrade` API.
- Wiki tab loads on hosted agents across machine restarts and across
  agent switches, without page reloads.

## Prerequisites

- Prod admin session (mint `luna_session` cookie; temp DB allowlist as needed).
- Render deploy via API (autoDeploy off) — deploy hook after merge to main.
- Marketplace publish credentials (`LUNA_MP_*` / marketplaces.com.ai) — verify
  which marketplace hosts plugin-wiki 0.7.0 first.
- Never touch `luna/` submodule (no change needed: jwt.py already honors
  `LUNA_JWT_SECRET`).

## Tasks

### Phase 1 — cloud: stable per-agent JWT secret

- [ ] `cloud/runtime/proxy_secret.py`: add `derive_jwt_secret(root_secret,
      agent_id)` (HMAC-SHA256 HKDF, info `luna-jwt-v1:{agent_id}` — distinct
      from proxy/relay derivations).
- [ ] `cloud/runtime/base.py`: `AgentSpec.jwt_secret: str = ""`.
- [ ] `cloud/provisioning/workflow.py`: derive and set `spec.jwt_secret`
      next to the proxy-secret derivation.
- [ ] `cloud/runtime/fly_machines.py` + `cloud/runtime/docker_local.py`:
      inject `LUNA_JWT_SECRET` into provision env when `spec.jwt_secret` set.
- [ ] `cloud/provisioning/env_manifest.py`: add `LUNA_JWT_SECRET` to
      `DYNAMIC_VARS` + `_PLACEHOLDERS` + platform entries (masked by the
      SECRET heuristic already).
- [ ] `cloud/api/admin_routes.py` `backfill_machine_env`: merge the derived
      `LUNA_JWT_SECRET` into the pushed env so
      `keys=LUNA_JWT_SECRET` rolls it out to machines missing it.
- [ ] Unit tests (`cloud/tests/`): derivation deterministic + per-agent
      distinct + distinct from proxy secret; provision env carries the var;
      backfill pushes it.

### Phase 2 — plugin-wiki 0.7.1: pane token fix

- [ ] `wiki-src/src/lib/auth.ts`: use the localStorage fallback ONLY when not
      embedded (`window.self === window.top`); embedded panes rely solely on
      the Shell postMessage (initial `getTokenAsync` already waits; the 401
      retry now genuinely waits for a fresh token instead of re-reading the
      stale shared key).
- [ ] Rebuild the pane (`wiki-src && npm run build` → `plugin_wiki/ui`).
- [ ] Bump 0.7.0 → 0.7.1 in `luna-plugin.toml`, `__init__.py`
      `PluginManifest`, `pyproject.toml`.
- [ ] `pytest` in plugin-wiki; commit in luna-plugins repo.
- [ ] Package + publish: `package_plugin.py` → `publish_plugin.sh` to the
      marketplace that hosts 0.7.0; verify `index.json` shows 0.7.1.

### Phase 3 — rollout (prod)

- [ ] Merge to main, push, deploy cloud to Render via deploy hook; wait healthy.
- [ ] Backfill fleet: `POST /api/admin/machines/env/backfill?keys=LUNA_JWT_SECRET`
      dry-run first, then live (one restart per machine; expected: all Fly
      agents updated).
- [ ] Push plugin upgrade to each agent with wiki installed via tenant
      `POST /api/p/plugin-marketplace/upgrade` (through the cloud proxy),
      or the machine's Marketplace pane if the direct call is refused.
      Verify installed version 0.7.1 per agent.

### Phase 4 — E2E verify (scenarios in `tests/042-wiki-auth-stability/`)

- [ ] S1 — wiki loads: open Rayla's and Starla's Wiki tab on luna.com.ai;
      graph renders, no 401.
- [ ] S2 — cross-agent switch: open agent A's wiki, then agent B's wiki in
      the same browser session; B must not 401 (the old stale-localStorage
      trigger).
- [ ] S3 — restart survival: restart one agent's Fly machine via the
      Machines API; re-open its wiki WITHOUT a page reload → pane recovers
      (fresh token via postMessage; server secret stable).
- [ ] Execution summary: `plans/042-wiki-auth-stability/execution-summary.md`.

## Risks / notes

- The backfill env update restarts each machine once and (by design, one
  last time) invalidates outstanding tokens — momentary 401s during rollout;
  panes recover via the 0.7.1 retry, shells via reload.
- `update_machine_env` merges and never wipes (029 backfill precedent);
  do NOT bulk-replace machine env.
- Working tree has unrelated uncommitted changes (gateway/billing WIP) —
  commit only files this plan touches.
- Local-runtime agents (e.g. Starla when running locally) keep a persistent
  `~/.luna/jwt_secret`, so bug 1 doesn't apply there; bug 2's fix covers them.
