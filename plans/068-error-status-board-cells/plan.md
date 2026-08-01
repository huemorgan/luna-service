# Plan 068 — Error list: monday-style status cells, resolved stays visible

## Problem
Plan 065 shipped triage state (open/resolved/regressed + notes + drawer), but the
list presentation defeats the point:
1. The default filter is `active` — **resolved groups vanish** from the list. The
   operator wants to SEE them, marked resolved.
2. The status renders as a small pill chip — hard to scan. Wanted: a
   **monday.com-style board cell** — the status color fills the entire cell,
   white bold label, instantly scannable.
3. Labels `open`/`regressed` don't match the operator's mental model:
   **new / resolved / not resolved** (not-resolved = was resolved, kept happening).
4. No way to see WHY something was closed/reopened without opening the drawer —
   wanted: **hover tooltip on the status cell** showing the resolve/reopen note,
   who, and when.

## No backend changes
065's API already returns per-row `status` (derived open/resolved/regressed),
`note`, `resolved_at`, `resolved_by_email`, and supports `?status=` filtering.
This is a UI-only change to `cloud/ui/src/pages/admin/ErrorsPage.tsx`.

## Changes
1. **Default filter → All statuses** (`statusF` initial `'active'` → `''`).
   Resolved rows stay in the list, visibly marked.
2. **Status labels** (display only; API values unchanged):
   open → `new`, resolved → `resolved`, regressed → `not resolved`.
3. **Monday-style cell**: the Status `<td>` drops padding; an inner block fills
   the whole cell with the status color, centered white semibold label.
   Colors (monday palette): new `#579bfc` (blue), resolved `#00c875` (green),
   not resolved `#e2445c` (red).
4. **Hover tooltip** on the status cell: the resolve/reopen note (reason),
   plus `by <email> · <when>` when present; for `not resolved`, an extra line
   "kept happening after resolve". Pure CSS (group-hover), no new deps.
5. Filter dropdown + header totals renamed to match (new / resolved /
   not resolved); totals gain a resolved count. Empty-state copy updated.

## Testing
- `cloud/ui` tsc + vite build clean; existing cloud pytest untouched (no API change).
- Visual: table screenshot with all three states.

## Rollout
Push to main → Render auto-deploys luna-service (Docker build compiles the UI
from source). No migration, no fleet impact.
