# Plan 020 — Image Defaults tab + plugin-picker redesign

## Why

Two problems with how image configuration works today:

1. **Image defaults are scattered and partly in the wrong place.** The "default
   model an image runs" is edited inside the **Key Registry** page (the model
   catalog's per-kind `recommended_default` selector). That is a credentials/
   catalog screen — picking the *default for a Luna image* does not belong
   there. The default plugin selection is hardcoded (`DEFAULT_SET_NAMES` in the
   UI + `plugin-set.toml` seed) with no admin control.

2. **The plugin-set picker lists every marketplace plugin with an on/off
   toggle.** The marketplace can hold hundreds of plugins; listing them all is
   the wrong shape. We want: show the plugins that **are** included (with a
   remove control) + a **search** to add others from the marketplace.

## What we build

1. A tabbed **Luna Images** area: **Images** (the existing list) and **Defaults**
   (new).
2. The **Defaults** tab is the home for admin-editable image defaults:
   - **Default model** (primary / fast) for new images — moved out of Key Registry.
   - **Default plugin set** baked into new images — same editor as the image config.
3. A redesigned plugin-set editor used in **both** the per-image config and the
   Defaults tab: an *included list* (name + version + remove) plus a
   *marketplace search* to add more. No more full on/off list.

## Decisions (made here, revisit if needed)

- **Storage:** new generic `app_settings(key TEXT PK, value JSONB, updated_at)`
  table; the image defaults live under key `image_defaults`. Generic so future
  singletons reuse it. Auto-created via `Base.metadata.create_all` + a heal line.
- **`DEFAULT_IMAGE_CONFIG` becomes resolved, not constant.** Keep the hardcoded
  base as `_BASE_IMAGE_CONFIG`; add `await _resolve_default_image_config(db)`
  that overlays the stored `image_defaults` (`models`, `plugin_set`). All call
  sites that merge defaults under an image's config switch to the resolver.
- **Model default fallback chain stays intact (no data loss).** Resolution order
  becomes: per-image `image_config.models` → stored `image_defaults.models` →
  catalog `recommended_default`. We do **not** drop the `recommended_default`
  column; we just remove its *editor* from Key Registry and make the Defaults tab
  the primary place to set it. This keeps Plan 018 semantics as the final
  fallback.
- **Search:** add an optional `?q=` filter to `GET /marketplace/catalog`
  (substring over name/description). The included-list still resolves
  version/sha256 from the full catalog.
- **Routing:** `images/defaults` is registered before `images/:imageId`
  (static beats dynamic in react-router v6 anyway). The per-image config page
  stays a drill-in; the tab bar shows on the Images list and Defaults pages.

## Phases

### Phase 1 — Backend: defaults store + resolver + search
- `cloud/db/models.py`: add `AppSetting` model (`key`, `value` JSONB, `updated_at`).
- `cloud/main.py`: heal line `CREATE TABLE IF NOT EXISTS app_settings (...)` (belt
  and suspenders; `create_all` already covers it).
- `cloud/api/admin_routes.py`:
  - Rename constant to `_BASE_IMAGE_CONFIG`; add `_get_app_setting`/`_set_app_setting`
    helpers and `async def _resolve_default_image_config(db)` overlaying
    `image_defaults`.
  - Replace the ~8 `{**DEFAULT_IMAGE_CONFIG, **(img.image_config or {})}` call
    sites with the resolver.
  - `GET /api/admin/defaults` → `{models, plugin_set}` (resolved) + `models_catalog`
    (enabled catalog models for the selector).
  - `PUT /api/admin/defaults` → validate (`_validate_plugin_set`, model shape),
    persist, audit.
  - `GET /api/admin/marketplace/catalog?q=` → substring filter.
- Unit tests: `cloud/tests/test_image_defaults.py` — GET/PUT round-trip, rejects
  connector in default set, resolver overlays stored defaults under base, catalog
  `?q` filter, image-config plugin_set still works.

### Phase 2 — Frontend: tabs, Defaults page, shared picker
- `cloud/ui/src/pages/admin/ImagesTabs.tsx`: small tab bar (Images / Defaults).
- `cloud/ui/src/components/PluginSetEditor.tsx`: shared editor — included list with
  remove + marketplace search-to-add; connectors shown disabled ("not bakeable").
- `cloud/ui/src/pages/admin/DefaultsPage.tsx`: model default selectors (primary/
  fast from enabled catalog) + `PluginSetEditor` for the default set; save → PUT.
- `cloud/ui/src/pages/admin/ImageConfigPage.tsx`: replace the toggle-list Plugin
  Set card body with `PluginSetEditor`.
- `cloud/ui/src/pages/admin/ServicesPage.tsx`: remove the per-kind default
  `<select>` block; leave the catalog; add a one-line pointer to Images → Defaults.
- `cloud/ui/src/App.tsx`: add `images/defaults` route; render `ImagesTabs` on the
  Images list + Defaults pages.
- Rebuild UI (`cd cloud/ui && npm run build`).

### Phase 3 — Tests + walkthrough
- `tests/020-image-defaults/`: scenario files (below).
- Run pytest (cloud) green; UI build green.
- Browser E2E of the admin UI (luna-service), screenshots read, per devprocess.
- Report.

## Acceptance
- Luna Images shows **Images** / **Defaults** tabs; switching works.
- Defaults tab edits default model + default plugin set; persists across reload.
- New/unconfigured images inherit the stored defaults (resolver).
- Both plugin editors show the included list + search-to-add + remove; neither
  lists the whole marketplace.
- Key Registry no longer shows the image-default model selector; catalog intact.
- Connectors remain non-bakeable (rejected on save) in both editors.
