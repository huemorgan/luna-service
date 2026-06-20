# Results 020 — Image Defaults tab + plugin-picker redesign

## Coded tests
- `cloud/tests/test_image_defaults.py` — 11 tests PASS (helpers, defaults GET/PUT
  round-trip, connector rejection, resolver overlay onto an image's config,
  catalog `?q` name+description search).
- Full cloud suite: **158 passed, 1 skipped** (no regression from the resolver
  refactor).
- UI `tsc -b && vite build`: green.

## E2E (browser, local cloud app + live marketplace)
Ran against a local control-plane (uvicorn + dockerized Postgres, seeded admin +
sample image) with the real `luna-marketplaces.onrender.com` catalog.

### 01 — Images / Defaults tabs — PASS
- `/admin/images` shows the **Images | Defaults** tab bar; Images active with
  underline; the list + "Build from branch" panel render unchanged.
- Clicking **Defaults** routes to `/admin/images/defaults`, marks Defaults active,
  shows the Image Defaults form. (screenshots `020-01`, `020-02`)

### 02 — Edit image defaults — PASS
- Primary model dropdown lists enabled catalog models (reasoning) with the catalog
  default flagged; set it to Claude Sonnet 4.5.
- Searched `files`, added `plugin-files` from the live marketplace.
- `GET /api/admin/defaults` → `{models.primary: anthropic/claude-sonnet-4-5,
  plugin_set: [plugin-files]}` — persisted.
- Resolver overlay verified: the sample image (empty `image_config`) inherits both
  the model and plugin_set via `GET /images/{id}/config`.

### 03 — Plugin picker redesign (both places) — PASS
- Image config Plugin Set card uses the included-list + search UX (no full on/off
  list). Inherited `plugin-files` shown with a remove control.
- Search `monday` → `plugin-monday` returned flagged **"connector — not bakeable"**,
  dimmed, button `disabled` (not addable). (screenshot `020-03`)
- Remove `plugin-files` → row gone; `GET /images/{id}/config` → `plugin_set: []`
  (explicit override persisted).
- Same editor confirmed on the Defaults page.

### Key Registry trim — PASS
- `/admin/services` Model catalog no longer shows the per-kind default selector;
  copy now points to "Luna Images → Defaults". Catalog list intact, no errors.

## Live walkthrough
This plan touches only the **admin control-plane UI** (no Luna agent runtime,
prompts, or tools), so the agent multi-turn walkthrough is N/A. The browser E2E
above is the live walkthrough for the changed surface, driven turn-by-turn with
screenshots + DOM snapshots read at each step.

## Connector guard coverage
The live official marketplace happens to host `plugin-monday`, so the disabled
connector row was verified in the browser. The save-side guard is also unit-tested
(`test_defaults_rejects_connector_in_set`, `_is_bakeable`).
