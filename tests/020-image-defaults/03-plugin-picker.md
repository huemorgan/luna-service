# 03 — Plugin picker redesign (both places)

## Steps
1. Open an image config page (`/admin/images/:id`) → **Plugin Set** card.
2. Confirm it shows the **included** plugins as a list, each with a remove
   control — NOT a full on/off list of the whole marketplace.
3. Use the **search** box: type a query (e.g. `chart`), see matching marketplace
   results, click one to add it. Confirm it appears in the included list.
4. Remove a plugin from the included list. Confirm it disappears + is saved.
5. Try to add a connector (e.g. `monday`/`render`/`cloudflare`): it must be shown
   as **not bakeable** and not addable (disabled), or rejected on save.
6. Repeat 2–5 on `/admin/images/defaults` (same editor).

## Expect
- Included list + search-to-add + remove in both screens.
- Search filters the marketplace (does not dump hundreds of rows by default).
- Connectors cannot be added (bakeable guard holds).
- Selections persist after reload in both screens.

## Pass/Fail
PASS if both screens use the included-list + search UX, adds/removes persist, and
connectors are blocked.
