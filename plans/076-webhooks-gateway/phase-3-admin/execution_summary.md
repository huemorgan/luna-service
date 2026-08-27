# Phase 3 — execution summary

Commit: `71839a3` ("076 phase 3: webhooks admin API + admin UI"), local only —
pushed in phase 4 together with phases 1–2.

## What shipped

**`cloud/api/webhook_admin_routes.py`** (new) — admin monitoring/management,
`require_admin` on every route (relay_routes pattern):
- `GET /api/admin/webhooks/endpoints[?agent_slug=]` — every minted hook joined with
  agent slug + name, including public URL and delivery stats. Secrets are never
  returned (they aren't even readable post-create by design).
- `GET /api/admin/webhooks/deliveries?limit=&agent_slug=` — queue-mode deliveries
  belonging to generic hooks only (`webhook_id LIKE 'hook_%'`); composio trigger
  deliveries stay on the existing `/api/admin/relay/deliveries`.
- `PATCH /api/admin/webhooks/endpoints/{id}` (`{"enabled": bool}`) and
  `DELETE /api/admin/webhooks/endpoints/{id}` — admin kill-switch per hook.

**Admin UI** (`cloud/ui/src`):
- `pages/admin/WebhooksPage.tsx` (new) — "Webhooks" page: registered-hooks table
  (agent, plugin/name, mode, copy-to-clipboard URL, delivery count, last status,
  last delivery, enable toggle, delete with confirm) and a queued-deliveries table
  with the same status pills as RelayPage. Plain fetch + 10 s poll, no new deps.
- `AdminLayout.tsx` — `{ to: '/admin/webhooks', label: 'Webhooks', icon: Webhook }`
  added to SERVICE_ITEMS (left pane, Services group) — the registry page Roy asked for.
- `App.tsx` — `/admin/webhooks` route.
- `MachinesPage.tsx` — the per-machine Webhooks tab now opens with a **Minted hooks**
  section (self-fetched via `?agent_slug=`), above the composio account-links and
  deliveries sections — so each agent's hooks are visible in its machine card too.

## Verification

- `cloud/tests/test_webhook_admin.py` — 6 tests: admin-gating (regular user
  rejected), agent join fields, `agent_slug` filter, deliveries filter excludes
  composio rows, patch/delete round-trip, 404 on bad id. All pass.
- Full suite: **796 passed, 9 skipped, 1 failed** — only the pre-existing billing
  clawback baseline failure. No regressions.
- `npm run build` in `cloud/ui` — clean build (existing chunk-size warning only).
- Visual check deferred to phase 4 on production (admin session requires real Google
  identity; the plan's production verification covers the page).

## Surprises / learnings

- `cloud/ui/dist` looked tracked, but only `index.html`/`favicon.svg`/`icons.svg`
  are committed — `dist/assets` is gitignored, and the tracked `dist/index.html`
  references a hashed asset that isn't in git. Conclusion: Render runs the UI build
  itself at deploy; the tracked dist files are stale artifacts. The local rebuild's
  `dist/index.html` change was deliberately reverted to keep the diff clean —
  committing it would pin a hash that doesn't exist in the repo.
- Every new module that imports `get_db_session` needs a conftest `_patch_db` entry
  (second occurrence this plan — phase 2 learning confirmed as a rule).

## Reassessment of remaining phases

- Phase 4 (deploy + production verification) unchanged: push phases 1–3 (3 commits)
  to huemorgan/luna-service main, Render autodeploys, migration 0016 applies on boot.
  Production smoke: admin page loads, mint via QA tenant device token, fire sync hook
  with machine stopped (wake + readiness), queue hook (forwarder + dead-letter path
  observed), then clean up QA hooks. Add: verify the new Webhooks nav item renders
  (this phase's UI had no browser check yet).
- Phases 5 (vanity domain) and 6 (Monday migration) remain optional/deferred.
- No PLAN.md changes required.
