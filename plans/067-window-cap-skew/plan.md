# Plan 067 — Context-window pulldown: gauge mismatch, cap not sticking, styling

## Symptoms (prod, reported 2026-08-01)

1. The context gauge reads "~215k / 200k tokens" while the picker shows GPT-5.5
   with "Max (1.05M)" — the gauge denominator ignores the model/selection.
2. Picking a window size in the pulldown doesn't stick — it snaps back to Max.
3. (Cosmetic) the pulldown is gray; should be purple like the selected-row
   highlight.

## Root cause of 1+2 — version skew, not a logic bug in 064

The fleet receives UI via **live plugin upgrades** (plan 063 upgraded
plugin-chat-ui fleet-wide on all started tenants with no image rollout), while
luna core only changes via a **machine-image rollout** (`scripts/rollout_image.py`
pin → build → promote). 064 was the first picker feature that needs core-side
support (luna 0.55.000: `window_caps` on GET /api/models/catalog + caps patch on
PUT /api/models + catalog-window fallback in `active_context_window()`).
064's EXECUTION.md records the rollout as "a separate step" — it never happened.

So tenants run a chat-ui bundle built against 0.55 sources on top of a
≤0.54.002 core:

- **Bug 1**: old `active_context_window()` returns `entry.context_window or
  200_000`; config writes recreate chain entries bare, so the gauge limit is the
  200k default for every model. (Fixed in 0.55.000 by the catalog fallback +
  cap-aware limit — needs the image rollout to reach tenants.)
- **Bug 2**: the caps-only write sends `{chain: [], window_caps: {...}}`. The
  old core's `SetModelChainRequest` has no `window_caps`; it sees an empty chain
  → `"No model(s) given for reasoning."` → HTTP 400 → the UI's optimistic state
  rolls back → the select snaps to Max. Also old `GET /api/models/catalog`
  returns no `window_caps`, so even a persisted cap could never display.

## Changes

### luna (0.55.001)
`ui/src/components/ModelPickerMenu.tsx`:
- **Skew-proofing**: render the window pulldown only when the core actually
  supports caps — `windowCaps != null` (the caller passes the *presence* of
  `window_caps` in the catalog response through; old cores omit the key). A
  pulldown that can neither read nor write caps must not render.
- **Styling (bug 3)**: select goes purple to match the selected-row highlight
  (`bg-luna-500/25`, `border-luna-400/60`, `text-luna-100`, hover/focus
  luna-300 accents).

### luna-marketplaces (plugin-chat-ui 0.4.1)
`marketplace-src/plugin_chat_ui/ui-src/src/views/ChatPanel.tsx`:
- `windowCaps` state becomes `Record<string, number> | undefined`; populate from
  `catalog.window_caps` **without** the `?? {}` coalesce so "old core" stays
  `undefined` and the picker hides the pulldown.
- Bump luna submodule to 0.55.001, rebuild `ui/chat.js`, vitest + chat-ui gate.

### luna-service
- Submodule bumps + this plan. No cloud code change (catalog windows already
  flow via LUNA_MODEL_CATALOG).

## Rollout (the actual fix for bugs 1+2 — requires prod access)

1. Push luna-marketplaces main → Render redeploys the marketplace with
   plugin-chat-ui 0.4.1 in the index.
2. Render one-off jobs on the control plane (srv-d8g5pd42m8qs73ekk2b0):
   - `rollout_image.py pin --plugin plugin-chat-ui --plugin-version 0.4.1 --sha256 <index>`
   - `rollout_image.py build --branch main --version 0.55.001`
   - `rollout_image.py promote --version 0.55.001`
   - `rollout_image.py verify --version 0.55.001`
3. Fleet plugin upgrade of installed plugin-chat-ui → 0.4.1 (same bulk-upgrade
   op as 063 used for 0.2.0).
4. Visual pass on a hosted tenant: gauge denominator matches the picked model's
   window; picking 100k sticks (and survives reload); pulldown purple.

## Non-goals
- The condense/margin math (shipped in 064, correct once the core rolls out).
- Fleet-rollout automation triggered from CI.
