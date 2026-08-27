# 076 — Generic webhook gateway (registry + relay + admin UI)

Companion to `luna-plugins/plans/010-plugin-webhooks/PLAN.md` (master plan) and the new
`plugin-webhooks` plugin (its own plan lives in `plugin-webhooks/plans/001-initial/`).

**Goal**: any tenant plugin can mint a stable public webhook URL through the control
plane. External systems POST to it; luna-service wakes the tenant's Fly machine, waits
for readiness, and delivers to the plugin route. Admin UI lists the registry (left-pane
Services page) and per-agent hooks (Machines card tab).

**Why no separate Render service**: the WhatsApp/Telegram gateways and the scheduler
exist for state luna-service can't hold (Baileys sessions, a clock). A webhook gateway
is a pure relay; luna-service already owns ingress, wake, per-agent secrets, and the
composio store-and-forward queue. A separate service would be a pass-through with its
own failure modes and would still call back here to wake/deliver.

**Composio**: tenant-side untouched. Server-side, `relay_deliveries` gains a nullable
`target_path`; the forwarder falls back to the legacy composio events path when NULL.
Composio becomes one producer into the now-generic queue.

## Design

- New table `webhook_endpoints`: agent_id, unique `hook_slug` (URL token), `name`,
  owning `plugin`, `target_path` (must start `/api/p/`), `mode` (`sync`|`queue`),
  per-hook `secret` (HMAC, returned once), `enabled`, delivery stats.
- Agent-facing mint API `/api/agent/webhooks/*` — device-token auth (same pattern as
  `scheduler_agent_routes.py`), registered bare **and** under `/proxy`.
- Public ingress `ANY /api/webhooks/hooks/{agent_slug}/{hook_slug}`:
  - sync (default): forward raw body + `x-luna-hook-timestamp`/`x-luna-hook-signature`
    (standard-webhooks HMAC with the hook secret) + `x-luna-proxy-secret` +
    `fly-force-instance-id`; on transport error wake via `_try_wake_agent` then
    **poll readiness** (new `_wait_machine_ready`, /healthz through internal_url,
    ≤45 s) then retry once; return machine response verbatim. GET supported for
    provider challenge handshakes.
  - queue: insert `relay_deliveries` row with `target_path`, 202; existing forwarder
    delivers with backoff/dead-letter.
- Admin API `/api/admin/webhooks/*` (require_admin): endpoints list (+agent filter),
  queued deliveries, stats, enable/disable/delete.
- Admin UI: `WebhooksPage` under the left-pane Services group; MachinesPage
  `WebhooksTab` gains a "Minted hooks" section above the composio links.

Trust model matches plan 035 D3: ingress does no auth of its own beyond slug
knowledge — a forged call dies at the plugin's HMAC check. 200 KB body cap.

## Phases

- **phase-0-baseline** — record pre-change test state (full cloud pytest run).
- **phase-1-db-and-relay** — `webhook_endpoints` model, alembic 0016 (new table +
  `relay_deliveries.target_path`), forwarder generalization. Tests.
- **phase-2-mint-and-ingress** — `webhook_agent_routes.py`, `webhook_routes.py`
  (sync+queue+wake+readiness), URL helper, main.py wiring. Tests.
- **phase-3-admin** — `webhook_admin_routes.py`, `WebhooksPage.tsx`, SERVICE_ITEMS
  entry, App.tsx route, MachineCard tab section. UI build.
- **phase-4-deploy** — push main → Render autodeploy (migration runs via
  `cloud/db/migrate.py` before uvicorn), verify on production: mint via a QA tenant,
  fire sync hook with machine stopped (wake+readiness), queue mode delivery,
  admin page live. Clean up QA hooks.

Execution summaries in each phase folder.
