# 042 — Execution summary

## What was accomplished

- **Stable per-agent JWT secret (bug 1).** Added `derive_jwt_secret()` to
  `cloud/runtime/proxy_secret.py` (HKDF-style HMAC-SHA256 off
  `CLOUD_TRUSTED_PROXY_SECRET`, info `luna-jwt-v1:{agent_id}` — distinct from
  proxy/relay derivations, nothing stored). `AgentSpec.jwt_secret` threads it
  from `provisioning/workflow.py` into the provision env of both
  `fly_machines.py` and `docker_local.py` as `LUNA_JWT_SECRET`; declared in
  `env_manifest.py` (masked). `backfill_machine_env` in `admin_routes.py`
  merges the derived value so the existing fleet could be rolled without
  reprovisioning. 4 new unit tests in `cloud/tests/test_jwt_secret.py`
  (21 passed, 1 skipped overall). Commit `049cb4e`, deployed to Render
  (`dep-d9c9cq6rnols73e2muc0` live).
- **Pane token fix (bug 2), plugin-wiki 0.7.1.** `wiki-src/src/lib/auth.ts`:
  when embedded in an iframe the pane now uses ONLY the Shell postMessage
  token; the origin-wide `localStorage['luna.token']` fallback survives solely
  for direct/dev opens, so a 401 retry genuinely waits for a fresh Shell token
  instead of re-reading the stale shared key. Version bumped in
  `luna-plugin.toml`, `PluginManifest`, `pyproject.toml`; pane rebuilt
  (`index-BcKwesnx.js`). Published to marketplace `official`
  (sha256 `8eadd348f830…`), luna-plugins commit `392f360`, tag `v0.7.1`.
- **Fleet rollout.** Upgraded plugin-wiki 0.7.0 → 0.7.1 on Rayla, PA and
  Starla via the tenant `plugin-marketplace/upgrade` API (all 200). Env
  backfill (`POST /api/admin/machines/env/backfill?keys=LUNA_JWT_SECRET`):
  dry-run showed all 20 fleet machines missing the key; live run updated
  19/20 in place, `nadavsh-obi` timed out starting but its env HAD applied —
  started manually, checks passing. Verified via the Fly Machines API that
  all 20 machines carry `LUNA_JWT_SECRET`.

## E2E results (scenarios in `tests/042-wiki-auth-stability/`)

No browser MCP tools were available in the executing session, so S1–S3 were
verified over authenticated HTTP through the real production path
(`luna_session` cookie → luna.com.ai cloud proxy → Fly machine), which
exercises everything except the pane's DOM rendering. Verified honestly as
such, not as a browser walkthrough:

- **S1 — wiki loads: PASS.** `GET /a/<slug>/api/p/plugin-wiki/graph?wiki=main`
  with a proxy-login Bearer token: Rayla 200 (20 nodes / 24 edges),
  Starla 200 (1 node). No 401.
- **S2 — cross-agent switch: PASS (API layer + shipped bundle).** Rayla's
  token against Starla's wiki → 401 (per-agent secrets distinct); Starla's
  own token → 200. Both agents serve the 0.7.1 bundle and it contains the
  `window.self !== window.top` embedded guard, so an iframed pane can no
  longer read the shared localStorage key that caused the poisoning.
- **S3 — restart survival: PASS.** Minted a Starla token, restarted machine
  `811099c97d9238` via the Machines API (healthy after ~80 s), reused the
  same pre-restart token → 200 on the first attempt. Pre-042 this was a
  guaranteed persistent 401.
- **Rehydrate check: PASS.** After the backfill restarted every machine,
  plugin-wiki reports `0.7.1 / marketplace / active` on all three agents —
  the managed override was restored from the tenant DB at boot (008.6 path).

## What we discovered

- The marketplace `/upgrade` route accepts image-set plugins: applying it
  lands a managed override the loader prefers, which let 0.7.1 ship without
  rebaking the machine image.
- `backfill_machine_env` + `update_machine_env` (merge, never wipe, restart
  in place) was the right rollout lever; the one failure (`nadavsh-obi`) was
  a stopped machine exceeding the 90 s start wait, not an env problem.
- Render deploy POST returns 202 with an empty body — a duplicate deploy was
  created while diagnosing that; the duplicate was deactivated, no impact.

## Things to consider

- The backfill restarts invalidated all outstanding tenant tokens one final
  time (by design). From now on, restarts keep tokens valid.
- A real browser walkthrough of S1–S3 (screenshot + DOM per devprocess) is
  still worth one pass when browser tooling is available; the HTTP-level
  evidence covers the auth mechanics but not pane rendering.
- Local-runtime agents keep a persistent `~/.luna/jwt_secret`; only bug 2's
  fix (0.7.1 pane) applies to them.
- luna-plugins has no git remote configured — commit `392f360` / tag
  `v0.7.1` exist only locally.
