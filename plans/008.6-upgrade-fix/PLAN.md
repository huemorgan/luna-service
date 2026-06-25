# 008.6 — Upgrade wipes installed plugins (re-hydrate from DB on boot)

> Proposal for **Luna's team** (the fix lives in the `luna` submodule, which is
> read-only from this repo). luna-service depends on it; nothing in `luna/` is
> edited from here.

## Bug

Upgrading a hosted machine (or any recreate) loses all marketplace-installed
plugins. The installed-plugin list and their data tables survive; the plugin
**code** is gone.

## Root cause

1. Marketplace plugins extract to the container's local disk:
   `MANAGED_DIR = Path.home()/".luna"/"managed_plugins"` (`luna/plugins/install.py`).
   `HOME` is unset in the image → `/root/.luna/managed_plugins`.
2. Hosted Fly machines have **no persistent volume** (luna-service
   `cloud/runtime/fly_machines.py` create payload has no `mounts`).
3. `update_machine_image` swaps `config.image` → Fly rebuilds the machine on a
   fresh rootfs. The new image only ships the baked set
   (`LUNA_PLUGIN_SET_DIR=/opt/luna/plugin-set`), not runtime installs.
4. Tenant Postgres is external → `PluginRow` rows + plugin tables persist.

Net: DB says "installed", disk has nothing → orphaned rows, missing tools.

## Fix — re-hydrate from the DB at boot

The DB is already the source of truth: each marketplace `PluginRow` stores
`config.source="marketplace"`, `config.marketplace_url`, `version`, and
`config.artifact_sha256` (stamped in `install_plugin`). On startup, reconcile
disk against the DB:

For each enabled `PluginRow` where `config.source == "marketplace"`:
- if its code is already present under `MANAGED_DIR` → load as today;
- else → re-run the existing integrity path
  (`fetch_and_verify(marketplace_url, name, version)` → `_extract` → `load_plugin`),
  verifying `sha256` against the stored `artifact_sha256`.

This reuses the existing install/integrity code; it just runs at boot for rows
whose artifacts are missing. After it, `discover_managed()` sees the restored
dirs and the normal loader proceeds.

### Where

In Luna's boot/plugin-load sequence, alongside `discover_managed()` /
`discover_plugin_set()` — add a `rehydrate_marketplace_plugins()` step that runs
before final registry assembly.

### Behaviour / edge cases

- **Offline / marketplace unreachable:** log + skip that plugin (don't crash
  boot); leave the row; retry next boot. Surface a "needs re-install" state if a
  status field exists.
- **sha256 mismatch on re-fetch:** refuse (same gate as install); mark the row
  failed; don't load stale/changed code silently.
- **Version pinning:** re-fetch the **recorded** version, not "latest", so an
  upgrade doesn't silently move plugin versions.
- **Idempotent:** present-on-disk → no network call. Cost is one boot-time
  reconcile, network only for missing artifacts.
- **Baked set unaffected:** image-baked plugins still load from
  `LUNA_PLUGIN_SET_DIR`; re-hydration only covers user/marketplace installs.

## Out of scope

- No persistent-volume requirement (this fix makes machines true cattle).
- No change to the install integrity model, marketplace client, or DB schema
  (reuses fields already written by `install_plugin`).

## luna-service side

Nothing required once Luna re-hydrates. Optional later hardening: attach a real
Fly volume and point `MANAGED_DIR`/`HOME` at it as a second layer — not needed
if boot re-hydration ships.

## Acceptance

- Install a marketplace plugin → upgrade the machine → the plugin's tools work
  again after boot with no manual re-install; its tables/data are intact.
- Marketplace unreachable at boot → server still starts; missing plugin is
  flagged, others load.
- Re-fetched artifact failing sha256 → not loaded; row marked failed.
