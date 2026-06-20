# Tests 020 — Image Defaults tab + plugin-picker redesign

Dojo-style E2E for the **luna-service admin UI** (not the Luna agent chat). You
are the test runner: open the admin UI in a browser, perform the steps, read the
DOM + screenshots, judge pass/fail.

## Setup
- Run the cloud app locally (or test against the deployed admin) signed in as an
  admin user.
- Marketplace (`luna-marketplaces.onrender.com`) reachable for the search box.

## Scenarios
- `01-tabs.md` — Images/Defaults tabs render and switch.
- `02-defaults-edit.md` — edit default model + default plugin set; persists.
- `03-plugin-picker.md` — new included-list + search-to-add UX in both places.

## Coded tests
- `cloud/tests/test_image_defaults.py` — defaults GET/PUT, resolver overlay,
  connector rejection, catalog `?q` filter.
