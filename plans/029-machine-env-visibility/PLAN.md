# Plan 029 — Machine env-var visibility

## Problem

We just discovered that **no running tenant machine has `LUNA_GATEWAY_URL` / `LUNA_GATEWAY_TOKEN`** (every machine reports "no gateway"), even though provisioning now injects them. The only way to find that out was to SSH into the control-plane container and read each Fly machine's config by hand. There is **no UI** to see what env vars a machine actually has, nor what every new machine gets by default.

Two asks:
1. **Per-machine**: an "Env vars" tab on each machine (admin → Machines) showing the env that machine is actually running with.
2. **Defaults**: an "Env vars" tab in the Defaults section showing the env template every new machine receives.

Dynamic / per-agent values (tokens, isolated DB URL, derived secrets) must be represented as **placeholders** (e.g. `{{per-agent device token}}`), never leaked. Secrets that have a concrete value on a live machine are **masked**.

## How machine env is assembled today (source of truth)

`provision/workflow.py::_provision_core` →
- `build_gateway_env()` (`cloud/gateway/provision_env.py`) → proxy base-URLs + per-agent device token + `LUNA_GATEWAY_URL`/`LUNA_GATEWAY_TOKEN` + connectors mode (+ legacy real keys) → `AgentSpec.llm_keys`
- adds `LUNA_COMPOSIO_WEBHOOK_SECRET` (derived per-agent)
- model heads + system catalog → `image_config.models`

`runtime/fly_machines.py::provision` then builds the final Fly `config.env`:
- static platform vars: `LUNA_ENV`, `LUNA_AUTH_MODE`, `LUNA_TRUSTED_PROXY_SECRET`*, `LUNA_DATABASE_URL`*, `LUNA_VAULT_MASTER_KEY`*, `LUNA_REDIS_URL`, `LUNA_CORS_ORIGINS`, `LUNA_LOG_LEVEL`
- `+ spec.llm_keys` (the gateway block above)
- `LUNA_DISABLED_PLUGINS` (from `image_config.plugins`)
- `LUNA_PRIMARY_MODEL` / `LUNA_FAST_MODEL` / `LUNA_MODEL_CATALOG`
- `+ image_config.env` overrides
- `+ files_env()` (`LUNA_FILES_*`, `TMPDIR`, scratch)

(* = secret and per-agent dynamic)

**Conclusion:** new machines DO get the gateway pair. Existing machines predate the change and need a re-provision / env-delta to pick it up. The visibility UI makes this obvious going forward (the per-machine tab flags expected-but-missing keys).

## Backend

New module `cloud/provisioning/env_manifest.py`:
- `classify(name) -> (secret: bool, dynamic: bool)` — single source of truth for which vars are secrets (masked) and which are per-agent dynamic (placeholder in the template).
- `mask(value) -> str` — `"•••• (N chars)"`, never the value.
- `async default_env_manifest(db, image_config) -> list[EnvEntry]` — the template every new machine receives, dynamic per-agent values rendered as placeholder strings, no token issuance, no secret materialization.
- `live_machine_env(fly_config_env, expected_names) -> {entries, missing}` — classify + mask the **actual** env from the Fly machine config; flag any expected template key that's absent (so a missing `LUNA_GATEWAY_URL` is visible at a glance).

`EnvEntry = { name, value: str|null, placeholder: str|null, source, secret: bool, dynamic: bool }`
- `source ∈ {platform, gateway, models, plugins, files, image-config}`

Endpoints (admin_routes, `require_admin`):
- `GET /api/admin/machines/{machine_id}/env` → resolve agent by `runtime_ref`, read live Fly `config.env`, classify+mask, plus `missing` vs the agent's expected manifest.
- `GET /api/admin/defaults/env` → `default_env_manifest(default_image_config)`.

## Frontend

- `MachinesPage` — add an `env` tab to each machine card (`TABS` + `EnvTab`), lazily fetching `/api/admin/machines/{id}/env`. Table: name · value (masked/placeholder) · badges (secret 🔒, dynamic, missing). Missing-expected keys shown as a warning strip at the top.
- `DefaultsTabs` — add an `Env vars` tab → new route `/admin/defaults/env`.
- New `DefaultEnvPage` — renders `DefaultsTabs` + the default manifest table, with a legend explaining placeholders.
- `App.tsx` — register `defaults/env`.

### Dynamic handling (the explicit ask)
Every dynamic per-agent var appears in the **defaults** table with a placeholder value like `{{per-agent device token (lsv1-…)}}` and a `dynamic` badge, so it's clear the value is injected at provision time rather than fixed. Secrets with a real value on a live machine are masked.

## Out of scope
- Editing env from the UI (read-only for now).
- Backfilling existing machines (separate action — `Update All to Main` / re-provision already exists; the tab just makes the gap visible).

## Tests / verification
- `tests/029-machine-env-visibility/SCENARIOS.md` — dojo-style: open a machine's Env vars tab (secrets masked, gateway keys flagged missing on old machines), open Defaults → Env vars (placeholders shown for dynamic vars).
- Local browser walkthrough before deploy.
