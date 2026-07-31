# 064 — Execution summary

Shipped as **luna 0.55.000** (`ec46146`, huemorgan/luna main) + **plugin-chat-ui
0.3.0** (`de49980`, huemorgan2/luna-marketplaces main). Cloud untouched (catalog
windows already flow via `LUNA_MODEL_CATALOG`).

Work was originally built against luna 0.48.006 and **rebased onto 0.54.002**
(366 commits). Two consequences discovered at rebase time:
- Core `ui/src/views/ChatPanel.tsx` was deleted on main (063 extracted the chat
  UI to plugin-chat-ui) — the ComposerModelSelect caps-threading moved to the
  plugin's own ChatPanel copy instead.
- The plugin imports `@luna/components/ModelPickerMenu` from the live luna core
  tree (not vendored), so the pulldown/(i) built in core IS the live picker;
  the marketplaces commit bumps its luna submodule b4bbd22 → ec46146 and
  rebuilds `ui/chat.js`.

## What shipped

**Core (`luna/agent/context.py`)**
- `_reasoning_entry()` — resolves the chain entry + raw window, **falling back to the
  model catalog** when the chain entry carries no `context_window`. This fixes a latent
  bug: config writes recreate `ModelEntry`s bare, so after any picker change the window
  silently reverted to the 200k default (Kimi K3's 1M was ignored).
- `model_max_window()` — the provider's hard ceiling, ignoring caps.
- `active_context_window()` — now `min(max, user cap)`.
- **Scaled-margin trigger** replaces flat-33k + 0.70: `effective_context_window() =
  min((1 − SOFT_WINDOW_MARGIN) × capped, max − CEILING_RESERVE_TOKENS)` with
  `SOFT_WINDOW_MARGIN = 0.05` (env `LUNA_WINDOW_SOFT_MARGIN`) and
  `CEILING_RESERVE_TOKENS = 24000` (env `LUNA_CEILING_RESERVE_TOKENS`).
  A 100k pick condenses at ~95k (5k gap), not ~47k. `EFFECTIVE_CONDENSE_THRESHOLD`
  removed; `should_condense` compares directly against the trigger point.

**Condense passes (`plugins/plugin_api/condense.py`)**
- Durable + idle triggers compare `used >= threshold × effective_context_window()`;
  `threshold` is now a fraction OF the trigger point (post-turn 1.0, idle 0.67 —
  preserves the old 0.50/0.75 ratio). Gauge `pending_condense` (app.py) same rule.

**Config (`luna/config/schema.py`, `plugins/plugin_config/__init__.py`)**
- `ModelsConfig.window_caps: {"provider:model": tokens}` + `window_cap_for()`.
- `_write_models` accepts a `window_caps` patch (null clears; floor `_WINDOW_CAP_MIN =
  50_000`; catalog-validated), persists in the `config_overrides` "models" row,
  reapplied on boot; exposed in `_read_models` and the manage_config schema (the agent
  can set caps too).

**API (`luna/schemas/api.py`, `plugins/plugin_api/app.py`)**
- `SetModelChainRequest.window_caps` (patch semantics; caps-only writes with empty
  chain are valid). `GET /api/models/catalog` returns current `window_caps`.

**UI (`ui/src/components/ModelPickerMenu.tsx`, `ui/src/views/ChatPanel.tsx`,
`ui/src/lib/api.ts`)**
- Selected row gets a compact window pulldown (tiers 100k/200k/1M/2M below the model
  max + "Max (…)"), with an (i) tooltip: smaller window = cheaper/faster, ideal for
  transactional agents; larger = big-data work; past the size Luna condenses.
- Row converted `<button>` → keyboard-accessible div (a `<select>` can't nest in a
  button). Menu max-height raised 26rem → 46rem (fits all rows).
- `setModelChain` carries the caps patch; ChatPanel state optimistic with rollback.

## Verification
- `uv run pytest tests/` — **zero new failures** (34 pre-existing failures are
  byte-identical with the change stashed); +7 new tests in
  `tests/064-context-window-selection/test_window_cap.py` (cap min/clamp, margin
  binding both ways, catalog fallback, junk caps ignored). 046 threshold tests
  rewritten for the new rule.
- UI: `tsc -b` clean, vitest 111/111, vite build OK.
- Re-verified after the rebase onto 0.54.002: full pytest zero new failures vs the
  origin/main baseline (one order-dependent flake ruled out by isolated runs on both
  trees); core ui tsc/vitest 100/100/build OK; plugin vitest 17/17, bundle rebuilt and
  greps for the new markup.
- NOT yet verified live in a browser (picker rendering/UX) — do a visual pass on a
  hosted tenant once the fleet picks up luna 0.55.000 + chat-ui 0.3.0 (rollout is a
  separate step: image build + `scripts/rollout_image.py` + plugin republish).
