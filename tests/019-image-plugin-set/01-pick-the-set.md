# 01 — Pick the set (admin UI)

**Status:** runnable now (no phase08 dependency — pure control-plane UI).

## Setup
- Local stack up (`docker compose -f docker-compose.local.yml up`), admin signed in.
- Official marketplace reachable (`https://luna-marketplaces.onrender.com/mp/official/`).

## Steps
1. Admin → Images → open an image's config.
2. Scroll to **Plugin Set (baked into image)**.
3. Confirm the marketplace catalog renders with a version per plugin.
4. Confirm connectors (`plugin-monday`, `plugin-render`, `plugin-cloudflare`) are
   **disabled** with a "connector — not bakeable" badge.
5. With no prior selection, confirm the curated leaf set
   (charts / web-access / files) shows as **default**-checked.
6. Untick `plugin-files`; tick nothing else. See the "Saved" indicator.
7. Reload the page → the selection sticks (files off, charts/web-access on).

## Pass
- Catalog loads; connectors un-tickable; selection persists across reload;
  saving a connector is impossible from the UI (and rejected by the API, 400).

## Evidence → `evidence/`
- `01-picker.png`, `01-after-reload.png`
