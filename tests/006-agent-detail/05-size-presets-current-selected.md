# 05 — Size Preset Dropdown

## Setup
- On `/dashboard/agents/{id}` for an agent currently sized at `shared-cpu-1x · 1024 MB`

## Steps
1. Locate the "Size" row in the Compute card
2. Inspect the `<select>` element — read all `<option>` values
3. Note which option has the `selected` attribute
4. Try clicking it / changing value

## Expected
- The control is a `<select>` populated with at least these presets, in order:
  - `shared-cpu-1x · 256 MB`
  - `shared-cpu-1x · 512 MB`
  - `shared-cpu-1x · 1024 MB` ← **selected by default for current agent**
  - `shared-cpu-2x · 2048 MB`
  - `shared-cpu-4x · 4096 MB`
  - `shared-cpu-8x · 8192 MB`
  - `performance-1x · 2048 MB`
  - `performance-2x · 4096 MB`
  - `performance-4x · 8192 MB`
  - `performance-8x · 16384 MB`
- Each option includes the approximate monthly cost as part of the label or as a hint
- The dropdown is **disabled** (or visually disabled and ignores changes) with a "Coming soon" badge / tooltip next to it
- Clicking does not trigger any API call and does not change anything

## Pass criteria
- ≥ 10 preset options visible
- Current size (`shared-cpu-1x · 1024 MB`) pre-selected
- "Coming soon" indicator visible near the control
- No network request triggered on attempted change

## Fail criteria
- Dropdown is functional (would actually try to resize — not in this phase)
- Current size not pre-selected
- Missing "Coming soon" indicator
