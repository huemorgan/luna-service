# 018 · Scenario 04 — Billing on 4xx + catalog-sourced pickers

## Part A — failed attempts are not billable

1. Trigger an off-catalog managed call (Scenario 03 step 2) a few times.
2. Open admin → Services → Usage (managed vs BYOK).
3. The off-catalog/404 calls may be **recorded** (visibility) but must show
   `billable=false` — never counted as billable tokens.
4. Cross-check: a successful in-catalog call shows `billable=true`.

**Pass:** 404/4xx rows are non-billable; only real ≥200/<400 calls are billable.
**Fail:** any 4xx row marked billable (the phantom input-only rows return).

## Part B — image + machine pickers come from the catalog

1. Open an image's config page → Models section.
2. The primary/fast dropdowns list **only catalog models** (filtered by kind),
   labelled, grouped by provider. No `o3`/`o4-mini`/`gpt-4-turbo`/old ids.
3. Open a machine card → Settings → Models. Same: dropdowns are catalog-sourced;
   "Inherit image default" present; selecting a model pushes it live.
4. Confirm the default shown matches the new `DEFAULT_IMAGE_CONFIG`
   (`claude-opus-4-6` / `claude-haiku-4-5-20251001`), not the brick id.

**Pass:** both pickers catalog-sourced, no stale ids, default is the new one.
**Fail:** any stale id; brick id shown as default; dropdown not catalog-driven.
