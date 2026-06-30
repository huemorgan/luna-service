# 033 — Two-step rebake: bake a sibling, then promote + replace

## Problem

Plan 032 added a one-click "Rebuild main" that rebaked the current Luna version
**in place** (`force=true`: delete the built record, recreate same version, carry
`is_main`). In practice this was fragile and scary:

- It mutates the live main image record while a build is in flight.
- If anything goes sideways (build fails, webhook ordering), `is_main` can land
  on the wrong record. Observed in prod: after a force rebake, main fell back to
  the older `0.21.001` while a built `0.21.003` sat non-main.
- One opaque button that "may or may not work" with no clear intermediate state.

## Goal

Split the rollout into **two clear, safe steps** the admin drives explicitly:

1. **Bake** — create a *new sibling image* from the same Luna version with the
   current defaults. Never touches the current main. Two images from the same
   Luna version are allowed (the sibling is tagged `…-r1`, `-r2`, … when the
   base version already has a built image).
2. **Promote** — once the sibling is built, one button promotes it to Main,
   migrates all agents to it, deletes the old main image, and reports what
   happened.

The banner walks the admin through these states: `bake → building → promote`.

## Scope

- `plugin_set` rollout only (same as 032). No machine/model changes.
- Rebake builds Luna **main HEAD** (what the workflow actually produces), so the
  sibling's base version = the current Luna version, not the old main's.

## Design

### Backend (`cloud/api/admin_routes.py`)

- **Remove `force`** from `build_image`; restore the original semantics (409 on a
  built same-version, delete+recreate only for `failed`/`pending` retries). New
  builds never set `is_main`.
- **Extract** `_trigger_github_build(image_id, version, branch, base_version)`
  (the workflow dispatch + failure handling) so build + rebake share it.
- **Extract** `_migrate_all_agents(main_version, registry_tag, admin, ip)` from
  `migrate-all` so promote can reuse it.
- **`POST /images/rebake`** — base = current Luna version; version = base if free,
  else `{base}-r{n}`; `is_main=False`; snapshots current defaults into
  `image_config.plugin_set`; dispatches the build. Never replaces an existing
  record.
- **`POST /images/{id}/promote-main`** — img must be `built`. Set it main (unset
  others), migrate all agents to it, and — only if migration had **zero errors**
  — delete the previous main image. Warm the new image. Returns
  `{promoted, migrated, errors, deleted_old}`.
- **`/defaults/stale`** also returns a rebake candidate:
  `rebake_state ∈ {none, building, ready}`, `rebake_version`, `rebake_image_id`
  (newest non-main main-branch image whose baked plugin_set == current defaults).
- **check-update** strips a trailing `-r\d+` so a sibling rebake doesn't look
  like a new Luna version.

### Frontend (`DefaultsStaleBanner.tsx`)

One smart banner with three states:

- **stale, no sibling** → amber, "Bake new image with current defaults" → `rebake`.
- **building** → amber spinner, "Baking v… — takes a few minutes", self-polls.
- **ready** → green, "Promote v… to Main (migrates agents, removes old main v…)"
  → `promote-main` (behind a confirm).

## Acceptance

- Clicking Bake creates a non-main sibling, current main untouched, build runs.
- When built, banner flips to Promote.
- Promote makes the sibling main, migrates agents, deletes old main, reports counts.
- No path mutates a built main record in place; `is_main` is always exactly one
  built image after promote.
