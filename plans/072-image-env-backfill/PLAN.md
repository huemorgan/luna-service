# 072 — image env defaults reach existing machines (code_run venv on the volume)

## Problem
Two gaps found 2026-08-17 while fixing the first hosted `code_run` failure
(plugin-inline-code-run plan 002, luna plan 078):

1. `PUT /api/admin/images/defaults` accepts an `env` block ("admin-stored env
   defaults for new machines"), and the env-manifest / drift view expects it,
   but provisioning never applied it: `_provision_core` composes the runtime
   spec from the image's raw `image_config` (`{plugin_set: [...]}`) plus only
   the `machine` block of the stored defaults. A default env var never reached
   a new machine.
2. `POST /api/admin/machines/env/backfill` pushes only the gateway block (+
   `LUNA_JWT_SECRET`); there is no way to roll a static image env var out to
   the machines that already exist, and no way to limit a run to a few agents.

Concretely: `LUNA_INLINE_CODE_RUN_VENV_DIR=/workspace/.code-run-venvs` (puts
the plugin's curated venv on the persistent volume so it is not rebuilt —
~10-60 s with egress — on the first `code_run` after every boot) could not be
delivered to any machine.

## Changes
- `cloud/provisioning/image_defaults.py`: `effective_env_overrides(defaults,
  image_config)` — stored `image_defaults.env` overlaid by the image's own
  `image_config.env`, stringified.
- `cloud/provisioning/workflow.py`: `effective_image_config["env"]` is set from
  it, so new machines get the admin default env (image entries win per key).
- `cloud/api/gateway_env_delta.py::_agent_image_config`: `env` merged one level
  deep (was: image's env dict replaced the default block wholesale).
- `cloud/api/admin_routes.py::backfill_machine_env`:
  - new `slugs=` (comma-separated agent slugs) filter;
  - the pushed env carries `image_config.env` (via `_agent_image_config`),
    `setdefault` so gateway/JWT-derived keys always win;
  - unchanged: only machines whose live env lacks a sentinel are touched, so
    `keys=LUNA_INLINE_CODE_RUN_VENV_DIR` targets exactly the machines missing it.
- Tests: `cloud/tests/test_image_env_072.py`.

## Rollout
1. Commit + push (also bumps the luna submodule to 078 / 0.82.004).
2. Deploy the control plane (Render deploy hook; autoDeploy is off).
3. `PUT /api/admin/images/defaults` with
   `env: {"LUNA_INLINE_CODE_RUN_VENV_DIR": "/workspace/.code-run-venvs"}`.
4. `POST /api/admin/machines/env/backfill?dry_run=false&keys=LUNA_INLINE_CODE_RUN_VENV_DIR&slugs=<the nine 0.82.x vaselin agents>` —
   `update_machine_env` merges and restarts each machine in place; machines
   that were stopped beforehand are stopped again afterwards.
5. Image 0.82.004 (luna 078): set main, `update-image` on the same nine
   machines, restore stopped state.
6. Verify on `vaselin-linearascent-promote`: machine env has the var; after a
   `code_run`, `/workspace/.code-run-venvs/curated-*/` exists.

## Notes
- The backfill still mints a fresh gateway token per touched machine (existing
  plan 029 behaviour); the old one is revoked only after the push succeeds.
- Not in scope: a UI for `slugs`, per-agent env overrides.
