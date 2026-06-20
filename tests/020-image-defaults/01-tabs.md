# 01 — Images / Defaults tabs

## Steps
1. Navigate to `/admin/images`.
2. Observe the top of the page.
3. Click the **Defaults** tab.
4. Click the **Images** tab.

## Expect
- A tab bar with **Images** and **Defaults** is visible at the top of the Luna
  Images area.
- On `/admin/images` the **Images** tab is active and the existing image list +
  "Build from branch" panel render unchanged.
- Clicking **Defaults** routes to `/admin/images/defaults`, marks **Defaults**
  active, and shows the defaults form (model defaults + default plugin set).
- Clicking **Images** routes back to the list.
- No console errors; no layout breakage.

## Pass/Fail
PASS if both tabs render, switch routes, and the correct panel shows for each.
