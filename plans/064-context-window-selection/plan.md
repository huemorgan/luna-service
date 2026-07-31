# Plan 064 — User-selectable context window (condense budget) per model

## Problem
Today the point at which Luna compacts a conversation is **derived entirely from the
selected model's catalog `context_window`** — the user has no say. `active_context_window()`
(`luna/luna/agent/context.py:342`) reads the reasoning chain head's `context_window`
(injected from the cloud registry via `LUNA_MODEL_CATALOG`), and the condense system
fires at a fixed **percentage** of it (`CONDENSE_THRESHOLD = 0.75`, effective `0.70`,
idle `0.50`), minus fixed reserves (`SUMMARY_OUTPUT_RESERVE = 20000` +
`CONTEXT_SAFETY_BUFFER = 13000`). So a Kimi K3 chat always runs against ~1M tokens of
window even when the user is doing short, transactional work that would be far cheaper
with a small window.

We want the user to **cap the window** per model from the composer picker, which
lowers per-turn token spend (smaller = cheaper/faster) or raises it deliberately for
large-data work (bigger = more context, higher cost).

## The mental model — corrected
The user's framing is ~80% right. Precise version:

- What's being chosen is **not "the model's context window"** (that's a hard provider
  limit we can't change) — it's a **condense budget**: a soft cap on how much history
  Luna keeps in play before it summarizes older turns. There is **no provider API to
  "shrink" a context window**; you control input size by what you send, and Luna already
  does that via condensing. So "if the model supports it another way, use that; else
  trigger condense" collapses to: **condensing is the mechanism, always.**
- **"200k for all models" is invalid** — GPT-4o / GPT-4o-mini are 128k
  (`cloud/gateway/model_registry.py:50,56`). A 200k cap on a 128k model would overflow
  the hard limit. The corrected rule (below) derives options from each model's real max.
- **"100k for all" is valid** — every model currently in the picker is ≥128k, and 100k
  leaves headroom on the smallest (128k). It's the safe universal floor. (If a <128k
  model is ever added, the derivation rule auto-drops 100k for it.)
- The chosen size is a **window cap**, not the literal condense-trigger point: the
  existing threshold/reserve math still applies on top, so condense fires *below* the
  cap. This is intentional (keeps output/system/tool headroom so we never overflow).

## Design

### Option derivation (per model)
Given standard tiers `T = [100k, 200k, 1M, 2M]` and a model max `M`:

```
options = sorted({ t for t in T if t < M } ∪ { M })
```

- GPT-4o (128k) → `{100k, 128k}` (128k labeled "Max")
- Grok 4.5 (500k) → `{100k, 200k, 500k}`
- Kimi K3 (1,048,576) → `{100k, 200k, 1M, 1.05M}`
- A hypothetical 1.2M model → `{100k, 200k, 1M, 1.2M}` (matches the user's example)

The largest option is always the model's exact max, labeled **"Max"**. Default (no
user choice) = **Max**, i.e. **current behavior — this feature is opt-in and
backwards-compatible.**

### Integration point + the margin rule (the important part)
Naively returning `min(model_window, cap)` and reusing the existing flat 33k reserve
(`SUMMARY_OUTPUT_RESERVE 20k` + `CONTEXT_SAFETY_BUFFER 13k`) plus the 0.70 threshold gives
a **~53k gap on a 100k pick** (condense at ~47k) — absurd. That flat reserve exists only
to protect the **model's hard ceiling** (the model needs room to generate its reply). When
the user's cap `N` is well below the model's real max `M`, there is no ceiling to protect,
so the gap should be tiny.

Replace the flat-reserve + 0.70 math (for the capped path) with a **scaled margin**:

```
OUTPUT_RESERVE ≈ 24k          # reply + system + tools room, only relevant near the ceiling
SOFT_MARGIN_PCT = 0.05        # ~5% "don't condense mid-thought" cushion (tunable)

condense_at(N, M) = min( (1 - SOFT_MARGIN_PCT) * N ,  M - OUTPUT_RESERVE )
```

- `0.95 * N` → the cushion scales with the pick: **5k on 100k, 50k on 1M**.
- `M - OUTPUT_RESERVE` → only binds when the cap approaches the model's true max
  (the "Max" option, or a small-ceiling model like GPT-4o at 128k).

| Model (max) | Pick | condense_at | Gap | Binding term |
|---|---|---|---|---|
| Kimi K3 (1M) | 100k | ~95k | 5k | `0.95·N` |
| Kimi K3 (1M) | Max | ~950k | ~50k | `0.95·N` |
| GPT-4o (128k) | 100k | ~95k | 5k | `0.95·N` |
| GPT-4o (128k) | Max (128k) | ~104k | ~24k | `M − OUTPUT_RESERVE` |

Implementation: `active_context_window()` still returns `min(entry.context_window, cap)`,
but `effective_context_window`/`should_condense` (`context.py:403-458`) switch from
`raw − 33k` then `× 0.70` to the `condense_at` rule above. Everything else
(`run_condense_pass`, the UI fullness gauge) keeps keying off the same effective number,
so the gauge stays truthful. The uncapped path (`cap = null` = Max default) is just the
`N = M` row — behavior for existing users is essentially unchanged.

**Safety note:** below the ceiling, a single huge turn can briefly overshoot `N` — this is
harmless (slightly more input sent once, no overflow). At the ceiling, the
`M − OUTPUT_RESERVE` term plus the existing in-turn reactive rescue
(`maybe_condense(force=True)`, `runtime.py:2686`) prevent a real overflow.

### Storage & scope
Model selection today is **global per-tenant** (config_overrides row `section="models"`,
`luna/plugins/plugin_config/__init__.py:363`), applied to "chats, playbooks, and
triggers." To stay consistent and avoid new per-conversation plumbing, store the cap the
same way: **per model, global**, as a new `window_cap` field on each `ModelEntry` in the
chain (`luna/luna/config/schema.py:11`). The cap travels with the model entry through
`reorderChainHead`, so switching models restores each model's own cap. `null` = Max.

### UI (composer picker — `luna/ui/src/components/ModelPickerMenu.tsx`)
For the **selected** model's row, to the right of its name and near the QUALITY/SPEED/COST
ranks, render:
1. A **compact pulldown** of the derived options ("100k", "200k", … "Max (1.05M)").
   Changing it calls the extended `setModelChain` (below) to persist `window_cap`.
2. An **(i) info affordance** to the right of the pulldown, tooltip copy:
   > **Context window** — how much conversation history Luna keeps in play each turn.
   > A **smaller** window costs less and runs faster (fewer tokens sent every message) —
   > ideal for transactional agents that don't need to remember or reprocess history.
   > A **larger** window lets Luna work across big documents or long histories, at higher
   > per-turn cost. When the conversation grows past this size, Luna condenses older turns
   > into a running summary.

   (Cost tie-in is deliberate — a bigger window multiplies the per-turn input-token bill,
   the same axis as the COST rank pips.)

## Changes
1. **`luna/luna/config/schema.py`** — add `window_cap: int | None = None` to `ModelEntry`.
2. **`luna/luna/agent/context.py:342`** — `active_context_window()` returns
   `min(entry.context_window, window_cap)` when `window_cap` set.
3. **`luna/plugins/plugin_config/__init__.py`** — `_apply_model_spec` / `_write_models`
   accept and persist `window_cap` per entry in the `"models"` override row.
4. **`luna/ui/src/lib/api.ts`** — `setModelChain` payload carries `window_cap` per entry.
5. **`luna/ui/src/components/ModelPickerMenu.tsx`** — derive options from `context_window`
   (already on `CatalogEntry`), render the pulldown + (i) on the selected row.
6. **`luna/ui/src/views/ChatPanel.tsx`** — thread the window-cap change into `onChange`
   → `setModelChain`; add `window_cap` to local `chains` state.
7. No **cloud** change needed — `context_window` already flows to the tenant via
   `LUNA_MODEL_CATALOG`. Standard tiers live client-side in `modelRanks.ts` or a small
   `contextTiers.ts`.
8. **Menu height (`ModelPickerMenu.tsx:175`)** — the picker capped at
   `max-h-[min(26rem,72vh)]` (~416px), forcing a scroll at ~7 of ~10 rows. Raised to
   `max-h-[min(46rem,88vh)]` so the full model list shows without scrolling where the
   viewport allows, still capping at 88vh on short screens. (Adding the per-row window
   pulldown makes fitting all rows on screen more valuable.)

## Open questions / decisions
1. **Small-cap headroom.** Fixed reserves total 33k. On a 100k cap that leaves ~67k, and
   0.70× → condense ~47k. For small caps this is aggressive. Options: (a) accept it;
   (b) scale `CONTEXT_SAFETY_BUFFER` proportionally for small windows. **Recommend (a)**
   for v1, revisit if users complain the small window condenses too early.
2. **Message-count backstop.** `CONDENSE_MESSAGE_COUNT = 40` fires independently of tokens
   (`context.py:44`). A transactional 100k agent may still condense at 40 messages.
   Leave as-is (a safety backstop), note in docs.
3. **Scope.** v1 = global per-model (matches today). If per-conversation is wanted later,
   add a nullable `window_cap` column on `Conversation` + a conversation-scoped endpoint —
   out of scope here.
4. **Selected value = raw cap vs literal condense point.** This plan treats it as the raw
   window cap (existing %/reserve math applies, condense fires below it). Confirm that's
   the intended UX vs. "condense exactly at N".

## Testing
- Unit (luna): option derivation (128k→{100k,128k}; 1.05M→{100k,200k,1M,max}); 
  `active_context_window` returns the min; `should_condense` fires earlier when a cap is
  set; persistence round-trip through `config_overrides`.
- UI: pulldown renders only on the selected row; options match the model max; (i) tooltip
  present; changing the pulldown persists and re-derives the gauge.
- Manual: pick 100k on Kimi K3, confirm the fullness gauge and condense fire against 100k,
  not 1M.

## Rollout
luna-only change (submodule), opt-in, default = Max (no behavior change until a user
picks a smaller size). Ship in a luna version bump; no cloud deploy required.
