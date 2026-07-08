# 036 — Default machine params

## Goal
Admins can set a **default machine config** (CPU kind, CPUs, memory, region) on
the Defaults page. It applies to every new machine, and is overridden per-field
by an image's own `image_config.machine`.

Resolution order (matches the existing image-config model):
`DEFAULT_IMAGE_CONFIG.machine  <  stored image_defaults.machine  <  image.image_config.machine`

## Current state (why this is needed)
- The `machine` block already exists in `DEFAULT_IMAGE_CONFIG`
  (`admin_routes.py:466`) and is editable **per image** via `ImageConfigPage`.
- But the **Defaults** page/API (`ImageDefaultsUpdate`, `GET/PUT /defaults`)
  only surface `models` + `plugin_set` — there is no way to set a default
  machine.
- And at **provision time** (`workflow.py`), the machine block comes straight
  from `image.image_config["machine"]` with hardcoded fallbacks in
  `fly_machines.py` (shared/1/1024/sjc). The stored defaults never reach
  provisioning. So even if we store a default machine, it wouldn't apply unless
  the image itself carried one.

Both gaps are fixed here.

## Changes

### Backend
1. **`cloud/provisioning/image_defaults.py` (new)** — single source of truth:
   `DEFAULT_IMAGE_CONFIG`, `IMAGE_DEFAULTS_KEY`, `overlay_config`,
   `get_stored_image_defaults(db)`, `resolved_default_config(db)`.
2. **`cloud/api/admin_routes.py`**
   - Import the above; drop the local `DEFAULT_IMAGE_CONFIG`/`IMAGE_DEFAULTS_KEY`
     copies. Keep `_overlay = overlay_config` + `_default_image_config` as thin
     aliases (preserves the `gateway_env_delta` import and the existing test).
   - Add `machine: dict | None` to `ImageDefaultsUpdate`.
   - Add `_validate_machine()` — mirrors the frontend Fly bounds (cpu_kind ∈
     shared/performance, cpus ∈ {1,2,4,8}, region ∈ allowed, memory within
     per-CPU-kind bounds and a known option). Reject invalid → 400.
   - `get_image_defaults` / `update_image_defaults`: include `machine` in the
     response and validate it on PUT.
3. **`cloud/provisioning/workflow.py`** — in `_provision_core`, overlay the
   resolved default machine **under** the image's machine before building the
   spec, so a default reaches the Fly guest when the image didn't set one and
   the image still wins per-field. Scoped to the `machine` block only (no change
   to models/plugins/env resolution).

### Frontend
4. **`cloud/ui/src/components/MachineConfigEditor.tsx` (new)** — extract the
   machine card (CPU kind / CPUs / memory / region selects, Fly RAM-per-CPU
   validity + clamping, cost estimate, Apply button, draft state) out of
   `ImageConfigPage`. Props: `value`, `onApply(machine)`, optional `title`/`note`.
5. **`ImageConfigPage.tsx`** — replace its inline machine block + machine state
   with `<MachineConfigEditor value={config.machine} onApply={m => save({machine:m})} />`.
6. **`DefaultsPage.tsx`** — add `machine` to the `Defaults` type + fetch, and
   render a "Default machine" `MachineConfigEditor` that saves via
   `PUT /defaults {machine}`.

### Tests
7. **`cloud/tests/test_image_defaults.py`** — machine round-trip via PUT/GET,
   invalid machine rejected (400), and (if fixtures allow) the provision overlay
   giving image machine precedence over the stored default.

## Verify & ship
- `pytest cloud/tests/test_image_defaults.py` + gateway tests green.
- `npm run build` (typecheck) in `cloud/ui`; do NOT commit `dist`.
- Commit, push, trigger a manual Render deploy, confirm `live`.
