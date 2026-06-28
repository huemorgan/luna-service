# 027 — Supported plugins marketplace picker — E2E scenarios

Browser-driven scenarios on the admin **Defaults** page (`/admin/defaults`). You are
the test runner: perform the steps, screenshot, read the DOM, judge pass/fail.

Prereq: admin UI reachable (local cloud server or the Render deploy), logged in as admin,
marketplace reachable so `/api/admin/marketplace/catalog` returns plugins.

## S1 — Supported card uses a marketplace search (not a free-text form)
1. Open Defaults, scroll to **Supported plugins**.
2. Click **Add supported plugin**.
3. **Expect:** a marketplace **search box** ("Search the marketplace…"), NOT three
   free-text inputs (no `plugin-monday` text field, no manual service `<select>`, no
   "marketplace url" field).
- PASS: a single search input that queries the marketplace.
- FAIL: the old free-text slug / service / url form is still shown.

## S2 — Search results show the plugin + its key provisioning
1. In the search box type `monday`.
2. **Expect:** a results dropdown with `plugin-monday` (name, version, description) and a
   **key badge** indicating the service it provisions (e.g. "monday key") — same shape as
   the default-set search.
- PASS: results list real marketplace plugins with a key/service badge.
- FAIL: no results, or no indication of the key service.

## S3 — Adding a connector auto-binds its service
1. Click `plugin-monday` in the results.
2. **Expect:** a new row in the Supported list bound to the **monday** service, showing the
   proxy/env control and a keyed/no-key badge, plus an "Install on…" action — without
   having typed a slug or picked a service manually.
3. Reload the page; the row persists.
- PASS: row present, service auto-bound from `key_service`, provisioning controls shown.
- FAIL: row missing, no service bound, or an error toast.

## S4 — Default plugin set unchanged
1. Scroll to **Default plugin set**; search its box for any bakeable plugin.
2. **Expect:** identical behavior to before — connectors still flagged "not bakeable",
   add still works.
- PASS: no regression in List A.
- FAIL: List A search broken or non-bakeable now addable there.

## S5 — Duplicate add is handled
1. Try adding `plugin-monday` to Supported again.
2. **Expect:** it shows "added" / is disabled in results, no 500, no duplicate row.
- PASS: graceful no-op.
- FAIL: duplicate row or error.
