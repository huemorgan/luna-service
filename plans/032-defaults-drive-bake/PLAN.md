# 032 — Defaults actually drive the bake + stale-defaults banner + rebake-main flow

## Problem

The admin **Defaults → Default plugin set** is cosmetic for baking. The build
never reads it.

- `build_image` creates the `LunaImage` row with an **empty `image_config`**.
- The build workflow fetches the set from `GET /images/{id}/plugin-set`, which
  reads `img.image_config.plugin_set` (empty) → **falls back to the committed
  `plugin-set.toml` seed**. The stored `image_defaults` is never consulted.
- `GET /images` and `GET /defaults` **overlay** current defaults at read time
  (`_image_dict`: `{**default_cfg, **img.image_config}`), so the UI *shows* the
  defaults' plugin_set as if it were baked — even though the bake used the seed.

Net effect: changing the Defaults plugin set does nothing to what gets baked.
That's why `plugin-files` showed `0.6.1` in Defaults but agents ran the seed's
`0.4.0`. The only way the seed and defaults stayed consistent was hand-editing
`plugin-set.toml`.

Two more gaps the user called out:
1. No signal that Defaults have drifted from the current main image (a rebake is
   required for plugin-set changes to land).
2. No guided "rebake main + switch" path — Build main + Set as Main + Migrate All
   exist but aren't tied to the drift signal.

## Goals

1. **Defaults drive the bake.** When an image is built, snapshot the resolved
   defaults' `plugin_set` into that image's `image_config`. The plugin-set
   endpoint then serves the defaults (not the seed), and each image permanently
   records exactly what it baked. The seed stays only as the offline / OSS / "no
   defaults set" fallback.
2. **Stale banner.** A sticky bar on the Defaults + Images pages when the current
   defaults' plugin_set differs from the **main** image's baked plugin_set:
   "Defaults changed since main image vX was built — rebuild to apply."
3. **Rebake-main entry point.** The banner's button triggers a main build; the
   existing Set as Main + Migrate All complete the switch.

## Scope

- **In:** plugin_set only (it is the thing physically baked into the Docker
  image). Models / machine / env stay dynamic (resolved at provision/runtime —
  not baked), so they are intentionally NOT part of "stale".
- **Out:** auto-promote / auto-migrate (kept manual — promoting main is a
  deliberate act); reworking the seed's role; per-image plugin_set overrides
  (already work via the Configure page and continue to win).

## Design

### Backend (`cloud/api/admin_routes.py`)

1. **Snapshot at build.** In `build_image`, before creating the `LunaImage`,
   resolve `cfg = await _default_image_config(db)` and set
   `image_config={"plugin_set": cfg.get("plugin_set", [])}` on the new row.
   - Empty defaults → snapshot `[]` → `get_image_plugin_set` still falls back to
     the seed (preserves today's behavior when no defaults are set).
   - Non-empty defaults → they win, and the bake is now reproducible/frozen.
2. **Stale-status endpoint.** `GET /admin/images/defaults-status`:
   - current = current defaults' plugin_set (normalized name+version set).
   - baked = the **main built** image's `image_config.plugin_set`, or the seed
     when that image predates the snapshot (empty image_config).
   - Return `{ stale: bool, main_version, main_image_id, current_count,
     baked_count }`. `stale` = sets differ (order-insensitive on name+version).

### Frontend

3. **`DefaultsStaleBanner` component** (shared): fetches `defaults-status`, renders
   a sticky amber bar when `stale`, with a **Rebuild main** button that POSTs
   `/api/admin/images/build` and then routes to `/admin/images`.
   - Mounted on `DefaultsPage` (top, under the tabs) and `ImagesPage` (top).
   - On Images, after the rebuild the existing Set as Main + Migrate All finish
     the switch; the banner clears itself once the new main matches.

## Acceptance

- Editing the Defaults plugin set → banner appears on Defaults + Images within a
  refresh; "Rebuild main" starts a build.
- A freshly built image's `image_config.plugin_set` equals the defaults at build
  time; `GET /images/{id}/plugin-set` returns the defaults (not the seed).
- After the new image becomes main, the banner clears (no drift).
- No-defaults-set case still bakes the seed (unchanged).

## Files

- `cloud/api/admin_routes.py` — snapshot in `build_image`; new `defaults-status`.
- `cloud/ui/src/components/DefaultsStaleBanner.tsx` — new shared banner.
- `cloud/ui/src/pages/admin/DefaultsPage.tsx` — mount banner.
- `cloud/ui/src/pages/admin/ImagesPage.tsx` — mount banner.
