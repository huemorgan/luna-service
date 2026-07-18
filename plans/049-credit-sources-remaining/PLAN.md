# 049 — Credit sources: show remaining, not used (align with the top bar)

## Problem

On the dashboard the **Total Account Credits** bar and the **CREDIT SOURCES**
breakdown (inside "Account & payment status") look like they contradict each
other:

- Top bar reads `8,570cr / 10,900cr left` and is yellow + blue.
- CREDIT SOURCES shows `Gift 41,000cr / 41,000cr · 100%` (green, full),
  `Bonus 1,100 / 1,100 · 100%` (purple, full), `Bucket 2,330 / 9,900 · 24%`
  (yellow), `Top-up 0 / 1,000 · 0%`.

The numbers and the colors both appear not to match.

## Root cause (verified — not a data bug)

The two views are consistent data-wise but render **opposite metrics**:

- Top bar (`CreditsBar`, `cloud/ui/src/pages/Dashboard.tsx`): colored length =
  **remaining**; `segments` come from `billing.balances` filtered to `v > 0`
  (`Dashboard.tsx:316-318`), and the denominator `monthTotal` is the original
  size of lots that still have credits (`Dashboard.tsx:326`). So gift/bonus
  (0 left) don't appear; only paid (yellow) + top-up (blue) do.
- CREDIT SOURCES (`SourceBar`, `cloud/ui/src/pages/billing/StatusBreakdown.tsx`):
  colored length = **used**; `pct = used/granted` (`StatusBreakdown.tsx:65`),
  and the caption prints `used cr / granted cr` (`:94`). It shows **every** lot,
  so the fully-spent gift (green) and bonus (purple) render as 100%-filled bars.

Net effects the user sees:
1. Same palette (`CREDIT_COLORS` in `cloud/ui/src/pages/billing/api.ts:229`,
   imported by both) but the **same color means opposite things** — yellow =
   "left" up top, "spent" in the middle.
2. Middle is dominated by green + purple (exhausted lots) that never appear up
   top, and its per-lot numbers (41,000 used, etc.) dwarf the 8,570 remaining.

Reading each bar as `remaining = granted − used` reconciles exactly to the top:
gift 0 + bonus 0 + bucket 7,570 + top-up 1,000 = **8,570**.

## Fix

Make CREDIT SOURCES speak the same language as the top bar: **remaining**, not
used.

In `SourceBar` (`StatusBreakdown.tsx`):
- Fill length = `remaining / granted` (currently `used / granted`).
- In-bar label = remaining `%` (i.e. `Math.round(remaining/granted*100)`), or
  drop the number-in-bar and keep just the caption — decide during build.
- Caption right side = `{remaining} left of {granted}` (currently
  `{used}cr / {granted}cr`). This matches the top bar's "left" framing and the
  BALANCE box hint.
- Keep the per-lot self-scaled full-width track (readability) — this is only a
  metric/label flip, not the earlier absolute-scale change.

Optional consistency polish (confirm with user before doing):
- Hide or visually de-emphasize fully-consumed lots (`remaining === 0`) so the
  middle stops being dominated by spent gift/bonus and better matches the top
  bar, which already omits them. Recommendation: keep them but render the empty
  (spent) portion muted so a 0-left lot reads as empty, not full.

No backend or data changes — `summary.balances` and the grants list are already
correct and consistent.

## Files

- `cloud/ui/src/pages/billing/StatusBreakdown.tsx` — `SourceBar` fill + labels.
- (No change needed to `Dashboard.tsx` / `api.ts`; palette already shared.)

## Risk

Low. UI-only, single component. Verify on the dashboard "Account & payment
status" panel that the four bars now sum (as remaining) to the top total and
that colors read consistently (yellow/blue dominant, green/bonus small or empty
when spent).

## Version

luna-service UI change — no `__version__` surface. Note in execution summary.

## Executed

Done in `SourceBar` (`cloud/ui/src/pages/billing/StatusBreakdown.tsx`): fill =
`remaining/granted`, in-bar label = remaining `%`, caption = `{remaining}cr left
of {granted}cr`. Fully-spent lots now render as (near-)empty bars, so the palette
means the same thing (remaining) as the top account bar. UI-only; Render rebuilds
the UI from source via Docker, so no committed build artifact is needed.
