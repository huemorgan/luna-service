# Phase 3 — admin API + admin UI

## Scope

**API — `cloud/api/webhook_admin_routes.py`** (new, require_admin, relay_routes pattern):
- `GET /api/admin/webhooks/endpoints[?agent_slug=]` — all minted hooks joined with
  agent slug + name; never returns secrets. Includes public_url and delivery stats.
- `GET /api/admin/webhooks/deliveries?limit=` — relay_deliveries rows belonging to
  generic hooks (webhook_id prefix `hook_`), joined with agent slug; body excluded.
- `PATCH /api/admin/webhooks/endpoints/{id}` — enable/disable from the admin side.
- `DELETE /api/admin/webhooks/endpoints/{id}`.
- Registered in cloud/main.py.

**UI** (committed dist — `npm run build` is part of the phase):
- `cloud/ui/src/pages/admin/WebhooksPage.tsx` — RelayPage pattern (plain fetch,
  10 s poll): endpoints table (agent, plugin/name, mode, enabled toggle, copyable
  public URL, delivery count / last status / last delivery), queue-deliveries table.
- `AdminLayout.tsx` SERVICE_ITEMS + `{ to: '/admin/webhooks', label: 'Webhooks',
  icon: Webhook }`; App.tsx route.
- `MachinesPage.tsx` WebhooksTab gains a "Minted hooks" section (self-fetched via
  `?agent_slug=`), above the composio account-links section.

## Verification
- New `cloud/tests/test_webhook_admin.py`: admin-only (regular user 403/redirect),
  listing + join, agent_slug filter, deliveries filter excludes composio rows,
  patch/delete.
- Full pytest suite back to baseline.
- `npm run build` succeeds; dist committed. Visual check happens in phase 4 on
  production (admin UI is session-auth'd against real Google identity; no local
  admin session available in the scratchpad).
