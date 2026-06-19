# Tests — 019 image-baked plugin set

Two layers:

1. **Unit** (`cloud/tests/test_plugin_set.py`, `scripts/tests/test_bake_plugin_set.py`)
   — fast, no network, run in CI.
2. **Dojo** (this folder) — real browser against a locally-built baked image.
   Gated on Luna `phase08` shipping the `LUNA_PLUGIN_SET_DIR` loader; until then
   the boot-with-plugins scenarios can't pass and are marked BLOCKED.

## Unit coverage (the contract)

- Catalog proxy `GET /api/admin/marketplace/catalog`
  - returns the marketplace `index.json` plugins as
    `[{name, version, description, sha256, bakeable}]`.
  - connectors (monday/render/cloudflare) come back `bakeable=false`.
  - tolerates marketplace down (returns cached or empty, never 500s the page).
- Saving `image_config.plugin_set`
  - a leaf-only selection persists and round-trips through GET config.
  - a selection containing a non-bakeable plugin is rejected (400).
  - an entry missing `sha256`/`version` is rejected (400).
- `bake_plugin_set.py` (against a `file://` fixture marketplace)
  - bakes **exactly** the selected set into `<out>/<pkg>/` (one top-level dir).
  - verifies each artifact's sha256; a tampered/incorrect hash **fails** the run.
  - writes `<out>/plugin-set.lock.json` = `[{name,version,sha256}]`.
  - empty/missing selection → falls back to `plugin-set.toml`.
- Image-config honesty: `/api/admin/plugin-meta` marks web-access/files/charts
  as `source=image-set`, not in-tree.

## Dojo scenarios (real browser, gated on phase08)

See the per-scenario files. Evidence → `evidence/`.

- `01-pick-the-set.md` — admin ticks a leaf subset, saves, reload shows it stuck;
  connectors are disabled with a reason.
- `02-baked-tenant-boots.md` — provision a local tenant on the baked image with
  **no marketplace configured / no egress**; charts + web-access + files show
  `active source=image-set` in Settings → Plugins; web_search + file_write +
  chart render all work in chat. **BLOCKED until phase08.**
- `03-fewer-is-fewer.md` — an image built from a 1-plugin selection bakes exactly
  one; nothing forces "all".
