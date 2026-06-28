# Plan 027 — Supported plugins: marketplace picker (match the default set)

## Problem

The **Supported plugins** card (`SupportedPluginsEditor` → `AddPluginForm`) adds plugins
via a **free-text form**: type a slug (`plugin-monday`), manually pick the key service,
optionally paste a marketplace URL. It only calls `/plugin-catalog/suggest` on blur to
*guess* the service — it never browses the marketplace.

The **Default plugin set** one card up (`PluginSetEditor`) already does the right thing:
a **marketplace search** that queries `/api/admin/marketplace/catalog`, lists real
plugins (name, version, description), and each catalog entry already carries
`key_service` (the gateway service whose key it needs). Click to add.

Expectation: the Supported list should add plugins **from the marketplace exactly like
the default set**, and each entry should show **what key provisioning we support** for it
(bound service + `proxy`/`env` + keyed status). The plumbing for that already exists; the
Supported add-flow just doesn't use it.

## Goal

Replace the Supported list's free-text add-form with the same marketplace picker the
default set uses, so adding a supported plugin = pick from the marketplace → service
auto-binds from `key_service` → row shows provisioning (service / proxy·env / keyed).

This is **almost entirely a frontend change.** The backend (catalog CRUD, `suggest_service`,
`key_service_for_plugin`, install hook) already supports it.

## What already exists (don't rebuild)

- `GET /api/admin/marketplace/catalog?q=` → `{ marketplace, plugins:[{name, version,
  description, sha256, bakeable, key_service}] }` (`admin_routes.py`). `key_service` is the
  per-plugin gateway service, `null` when the plugin needs no external key.
- `POST /api/admin/plugin-catalog` already: validates the slug, runs `suggest_service`, and
  **auto-fills `service_slug` from the suggestion when not supplied** (`plugin_catalog_routes.py`).
- Each rendered row already shows `KeyControls` (service picker + proxy/env + keyed/no-key
  badge) and `InstallControl` (`SupportedPluginsEditor`, `pluginKeys.tsx`).
- Install hook needs `entry.marketplace_url` to be the **marketplace base** (it POSTs
  `{marketplace_url, name}` to `/api/p/plugin-marketplace/install`), which is the
  `marketplace` field of the catalog response — not a per-plugin page URL.

## Changes

### C1. Extract a shared marketplace picker (frontend)
Pull the search box + results dropdown out of `PluginSetEditor` into a small reusable
`MarketplacePicker` component (`cloud/ui/src/components/MarketplacePicker.tsx`):
- props: `onPick(plugin: CatalogPlugin & { marketplace: string })`, `excludeNames: Set<string>`,
  `allowNonBakeable: boolean`, `placeholder?`.
- internally fetches `/api/admin/marketplace/catalog?q=`, debounced (reuse current logic).
- each result shows name, `v{version}`, description, and a **key badge** derived from
  `key_service` (e.g. `monday key` / `no key needed`) so the admin sees the provisioning
  before adding.
- refactor `PluginSetEditor` to consume it (default set keeps `allowNonBakeable=false`,
  so connectors stay "not bakeable"). No behavior change for List A.

### C2. Rewrite the Supported add-flow to use the picker (frontend)
In `SupportedPluginsEditor`, replace `AddPluginForm` with `MarketplacePicker`
(`allowNonBakeable={true}` — supported/opt-in plugins are mostly connectors that aren't
baked). On pick:
- `POST /api/admin/plugin-catalog` with `{ plugin_name: p.name, tier: "supported",
  display_name: p.name, marketplace_url: p.marketplace, service_slug: null }` — let the
  server's suggester fill the service from `key_service`/`KNOWN_SERVICES`.
- then `onChanged()` to refetch.
- drop the free-text slug input, the manual service `<select>`, and the manual URL field
  entirely.
- keep the existing rows (KeyControls + proxy/env + InstallControl + remove) — that's the
  "indicate what key provisioning we support" surface, and it already works.

### C3. Backend (verify-only, minimal)
- Confirm `POST /plugin-catalog` returns a sensible 409 path when re-adding an existing
  plugin (already does) so the picker can show "added" instead of erroring.
- No model/migration change. No new endpoint.
- (Optional polish) include `key_service` in the create response so the row can render the
  suggested service immediately without waiting for the catalog refetch — skip if the
  refetch is fast enough.

## Out of scope
- Backend provisioning logic, install hook, suggester map (all unchanged).
- The Default plugin set's behavior (only refactored to share the picker).
- User-initiated (non-admin) installs.

## Workstreams
- **C1** Extract `MarketplacePicker`, refactor `PluginSetEditor` onto it.
- **C2** Swap `AddPluginForm` → `MarketplacePicker` in `SupportedPluginsEditor`; wire the
  create POST with `marketplace_url = catalog.marketplace`.
- **C3** Verify create/409 + suggestion auto-fill end-to-end.

## Test plan
- Unit/integration (`cloud/tests/test_plugin_catalog.py`): adding a known connector
  (`plugin-monday`) with no `service_slug` auto-binds `monday`; unknown plugin lands with
  `needs_review` / no service; duplicate add → 409.
- Build the UI (`cloud/ui` → `npm run build`) and confirm `dist` updates.
- Dojo / live walkthrough (per `agent-live-walkthrough` skill): on the Defaults page, the
  Supported card searches the marketplace, adding `plugin-monday` shows it bound to the
  monday service with proxy/keyed state and an "Install on…" action — identical UX to the
  default set.

## Acceptance
- No free-text slug / manual URL inputs remain in the Supported card.
- Adding a supported plugin is "search marketplace → click → bound + provisioning shown",
  matching the default plugin set.
