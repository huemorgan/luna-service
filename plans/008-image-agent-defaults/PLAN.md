# Plan 008 — Image Agent Defaults

## Goal

Add a detail/config page for each Luna Image so admins can set the defaults
that agents provisioned with this image will use: machine size, region, LLM
models, enabled plugins (with toggle switches), and environment overrides.

## Prior work (stashed)

Partial backend work was started without plan approval and stashed:
`git stash list` → "WIP: image config - unapproved, needs plan".
Contains: `image_config JSONB` column, `DEFAULT_IMAGE_CONFIG`, GET/PUT
endpoints, `_image_dict` serialization. Will be unstashed and refined
during implementation.

---

## Phase 1 — Data model + API

### 1a. `LunaImage.image_config` JSONB column

New nullable JSONB column on `luna_images`. Stores overrides only; the
server merges with `DEFAULT_IMAGE_CONFIG` on read.

Schema:

```json
{
  "machine": {
    "cpu_kind": "shared | performance",
    "cpus": 1,
    "memory_mb": 1024,
    "region": "sjc"
  },
  "models": {
    "primary": { "provider": "anthropic", "model": "claude-sonnet-4-20250514" },
    "fast":    { "provider": "anthropic", "model": "claude-sonnet-4-20250514" }
  },
  "plugins": {
    "plugin_vault": true,
    "plugin_memory": true,
    "plugin_identity": true,
    "plugin_mcp": true,
    "plugin_web_access": true,
    "plugin_funnelfighters": true,
    "plugin_brain": true,
    "plugin_files": true,
    "plugin_meta": true,
    "plugin_approvals": true,
    "plugin_web": true
  },
  "env": {}
}
```

### 1b. Migration

Add column via `ALTER TABLE luna_images ADD COLUMN IF NOT EXISTS image_config JSONB`
in the lifespan migration block.

### 1c. API endpoints

- `GET  /api/admin/images/{id}/config` → merged config
- `PUT  /api/admin/images/{id}/config` → patch-merge update
- `_image_dict` includes `image_config` in serialization

---

## Phase 2 — Image Config UI

### Navigation

- Click `>` chevron on ImageCard → navigates to `/admin/images/:id`
- New route added to App.tsx inside the admin layout
- Back arrow to return to image list

### Page layout

Top section: image build info (version, status, SHA, dates) — read-only.

Below: config sections in cards.

### 2a. Machine section

Card with title "Machine". Dropdown/select controls:

| Field      | Options                                          |
|------------|--------------------------------------------------|
| CPU Kind   | `shared`, `performance`                          |
| CPUs       | 1, 2, 4, 8                                      |
| Memory     | 256 MB, 512 MB, 1 GB, 2 GB, 4 GB                |
| Region     | sjc, iad, lhr, ams, cdg, nrt, sin, syd, gru     |

### 2b. Models section

Card with title "Models". Two rows:

- **Primary** — provider dropdown (anthropic, openai) + model text input
- **Fast** — provider dropdown + model text input

### 2c. Plugins section

Card with title "Plugins". List of all plugins, each row:

- Plugin name (human-readable)
- Short description
- Toggle switch (green on / gray off, matching the user's screenshot)
- `plugin_web` and `plugin_approvals` shown as "Required" — toggle disabled

### 2d. Environment overrides

Card with title "Environment". Key/value rows:

- Each row: text input (key) + text input (value) + delete button
- "Add variable" button at bottom
- Empty by default

### Auto-save

All controls save on change via `PUT /api/admin/images/{id}/config`.
Brief "Saved" toast/indicator on success.

---

## Phase 3 — Wire into provisioning

When `FlyMachinesRuntime.provision()` creates a new machine:

1. Load the main image's `image_config`
2. Use `machine.cpu_kind`, `machine.cpus`, `machine.memory_mb` for `guest`
3. Use `machine.region` for region
4. Pass `plugins` config as `LUNA_DISABLED_PLUGINS` env var (comma-separated
   list of disabled plugin names)
5. Pass `models` config as `LUNA_PRIMARY_MODEL` and `LUNA_FAST_MODEL` env vars
6. Merge `env` overrides into the machine's environment

This phase is minimal wiring — no per-agent override system yet.

---

## Out of scope

- Per-agent config overrides (future)
- Volume configuration (phase 004)
- Auto-stop policy (future)
- Cost estimation display (future)
