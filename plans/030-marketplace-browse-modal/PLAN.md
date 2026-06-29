# Plan 030 — Marketplace browse modal

## Goal
Add a "browse the whole marketplace" popup, reachable from an icon to the right of
the existing marketplace search bar, in BOTH the Default plugin set and the
Supported plugins editors. The popup shows the full marketplace inventory, lets
you filter, indicates per-plugin external-key support, and greys out + sinks the
already-selected plugins to the bottom so the rest are easy to browse.

## Scope (frontend only)
Backend already serves everything we need: `GET /api/admin/marketplace/catalog`
(no `q`) returns the full list with `bakeable` and `key_service` per plugin. No
API changes.

## DRY
Both editors (`PluginSetEditor`, `SupportedPluginsEditor`, and the image-level
`PluginSetEditor` on `ImageConfigPage`) already render the shared
`MarketplacePicker`. So the feature is added once, inside `MarketplacePicker`, and
lands everywhere automatically.

## UX
- Search row becomes: `[ search input .......... ] [ 🛍 browse icon ]`.
- Icon opens a centered modal overlay (click backdrop / X / Esc to close).
- Modal top: a filter text input + filter pills `All` / `Needs key` / `No key`.
- Body, two groups:
  - **Available** (addable): plugins not yet selected and allowed for this list
    (the baked set blocks non-bakeable connectors). Click a row → add. Modal
    stays open so you can add several; the row then moves to the greyed group.
  - **Already added / unavailable** (greyed, at the bottom): selected plugins
    (`added`) and, for the baked set, non-bakeable connectors (`not bakeable`).
- Each row shows: name, `v<version>`, a key badge (`<service> key` when the
  plugin can use an external key, else `no key needed`), and a connector badge
  for non-bakeable plugins. Description underneath.

## Filters
- Text: substring match on name + description.
- Key: `all` (default) · `needs` (`key_service` set) · `none` (no key).

## Files
- `cloud/ui/src/components/MarketplacePicker.tsx` — add the icon button + modal +
  filter state + full-catalog fetch on open. No changes needed in the two
  editors (they pass `excludeNames` / `allowNonBakeable` / `onPick` already).

## Acceptance
- Defaults page: icon next to the search opens the modal; full inventory listed;
  selected plugins greyed at the bottom; key badges correct; text + Needs/No-key
  filters work; clicking an available plugin adds it (and it sinks to the bottom).
- Supported plugins: same modal/behaviour, connectors addable.
- `npm run build` clean, no lint errors.
