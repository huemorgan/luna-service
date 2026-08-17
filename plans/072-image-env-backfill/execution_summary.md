# 072 — execution summary (2026-08-17)

## Done
- `cloud/provisioning/image_defaults.py`: `effective_env_overrides()`.
- `cloud/provisioning/workflow.py`: `_provision_core` applies stored default env
  (image env wins per key).
- `cloud/api/gateway_env_delta.py::_agent_image_config`: `env` merged one level.
- `cloud/api/admin_routes.py::backfill_machine_env`: `slugs=` filter; pushes
  `image_config.env` (setdefault under gateway/JWT keys).
- Tests `cloud/tests/test_image_env_072.py` (3). Cloud suite: 760 passed,
  9 skipped, 1 pre-existing failure (clawback test, unrelated).
- Commit `523cfbe` on `origin/main` (includes luna submodule → `fb3220c`,
  0.82.004). Render deploy `dep-da1l6sjm8hqs73b9uau0` live.

## Rollout
- `PUT /api/admin/defaults` env →
  `{LUNA_DB_POOL_SIZE: 2, LUNA_DB_MAX_OVERFLOW: 3, LUNA_INLINE_CODE_RUN_VENV_DIR: /workspace/.code-run-venvs}`.
- `POST /api/admin/machines/env/backfill?dry_run=true&keys=LUNA_INLINE_CODE_RUN_VENV_DIR&slugs=<9>` →
  9 `would_update`. Then `dry_run=false`: the call outlives Cloudflare's 100 s
  edge timeout (HTTP 524) but keeps running server-side; each machine takes
  ~3-5 min (`update_machine_env` restarts + `_wait_healthy`). All nine machines
  now carry the var (`fly machine status --display-config`).
- Image 0.82.004 set main and rolled to the same nine machines; the four that
  were stopped before are stopped again.

## Verified on `vaselin-linearascent-promote`
Machine env has `LUNA_INLINE_CODE_RUN_VENV_DIR=/workspace/.code-run-venvs`;
luna 0.82.004 `get_env` returns it; the plugin's `default_venv_root` resolves to
it and `/workspace/.code-run-venvs/curated-…` exists on the volume.

## Follow-ups
- Backfill runs > 100 s trip Cloudflare 524 for the caller; a background job +
  status endpoint would make it observable (not blocking — the run completes).
- Route note: image defaults live at `/api/admin/defaults`, not
  `/api/admin/images/defaults` (the latter matches `/images/{image_id}` → 500).
