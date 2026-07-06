# 035 — Scheduler: always-on trigger service + plugin (luna-service end)

**Status:** Phases A–D EXECUTED (2026-07-06) — config, fire relay, agent
self-service (+ `/proxy` alias), admin proxy routes, and the left-nav
Scheduler page are live in-tree with tests (`cloud/tests/test_scheduler.py`,
`test_scheduler_agent.py`). Phase E (catalog entry) waits on the plugin being
published; Phase F dojo waits on the service deploying to Render and the two
`CLOUD_SCHEDULER_*` env vars being set.
**Model:** the WhatsApp split (034 / 034.1). A standalone always-on service on
Render owns the clock; a marketplace plugin (`plugin-scheduler`) owns the UX and
fires work inside each Luna; luna-service owns connect, the fire relay, and an
admin monitoring page in the left nav.
**Supersedes:** `plans/023-external-scheduler` (which put the ticker inside the
control plane). The clock now lives in its own service — same reasoning that
gave WhatsApp its own gateway: independent deploys, independent failure domain,
and the control plane stays a control plane.
**Companions (handoff files for the NEW project — develop there, not here):**
- `scheduler-service-plan.md` — the `luna-scheduler` service (new repo, Render)
- `scheduler-plugin-plan.md` — `plugin-scheduler` for the marketplace

## The shape

```
┌──────────── luna-scheduler (new repo, Render, ALWAYS-ON) ────────────┐
│  accounts (one per Luna, per-account HMAC secret)                     │
│  triggers (cron/NL, tz, action_type, target, enabled, next_run_at)    │
│  ticker → due triggers → signed fire POST (retry, dead-letter)        │
│  /stats + /accounts (admin key) · /accounts/{id}/triggers (HMAC)      │
└───────┬───────────────────────────────────────────────▲──────────────┘
        │ fire (HMAC, fire_id)                          │ trigger CRUD (HMAC)
        ▼                                               │
┌── luna-service (THIS repo — what this plan builds) ───┼──────────────┐
│  /api/webhooks/scheduler/{slug}/fire  → wake + forward raw to machine │
│  /api/agent/scheduler/connect         → account + secret (tenant tok) │
│  /api/admin/scheduler/*  +  left-nav Scheduler page (monitoring)      │
└───────┬───────────────────────────────────────────────▲──────────────┘
        ▼                                               │
┌── tenant Luna machine (Fly, may sleep) ───────────────┴──────────────┐
│  plugin-scheduler: tools (agent + playbook callable), settings tab,   │
│  /api/p/plugin-scheduler/fire → emits playbook.run.requested or       │
│  synthetic message.received {channel:"scheduler"} → normal agent loop │
└───────────────────────────────────────────────────────────────────────┘
```

## Decisions

- **D1 — Standalone service owns the clock and the trigger store of record.**
  Tenant machines sleep; the control plane should not accrete background loops.
  A dedicated Render service (like `luna-wa-gateway`) ticks, stores triggers,
  and delivers fires. luna-service never parses cron and never ticks.
- **D2 — Plugin ↔ service is direct, per-account HMAC.** Trigger CRUD from the
  plugin goes straight to the scheduler service signed with the account secret
  (exactly like plugin-whatsapp `/send`). The control plane is not in the CRUD
  path — it only provisions the account (admin key stays server-side only).
- **D3 — Fires route through a luna-service relay, not direct to Fly.** Copy
  `whatsapp_inbound_relay` (`cloud/api/whatsapp_routes.py:142`): the service
  POSTs `/api/webhooks/scheduler/{agent_slug}/fire`; we forward raw bytes +
  HMAC headers to the machine with the Fly routing header and wake-on-sleep.
  The relay does no auth of its own — a forged fire dies at the plugin's HMAC
  check. Fires are idempotent on `fire_id`, so wake-and-retry-once is safe.
- **D4 — Connect is plugin-initiated self-service (034.1 lesson, not 034).**
  Installing the plugin is the whole setup. The plugin calls
  `POST {LUNA_GATEWAY_URL}/api/agent/scheduler/connect` with the tenant token;
  we create the service account (admin key), return `{account_id, secret,
  service_url}`; the plugin stores them in its vault. No admin visit, no env.
- **D5 — The scheduler fires events; work runs in the normal loop.** A fire
  becomes `playbook.run.requested {name, inputs}` or a synthetic
  `message.received {channel:"scheduler"}`. Approvals, running indicator,
  Stop, and cost accounting all apply unchanged.
- **D6 — Admin page is monitoring-only** (034.1 rule): service vitals, fleet
  trigger list, fire history. No admin-side create/connect actions.

## Phase A — Config

`cloud/config.py` (`env_prefix="CLOUD_"`), plus `.env.example` and the
production Render env:

- `scheduler_service_url` → `CLOUD_SCHEDULER_SERVICE_URL`
- `scheduler_service_admin_key` → `CLOUD_SCHEDULER_SERVICE_ADMIN_KEY`

Unset ⇒ admin page shows a clean "not configured" empty state; connect
returns 503 with a clear message.

## Phase B — Fire relay (public webhook)

`cloud/api/scheduler_routes.py`, `relay_router`:

- `POST /api/webhooks/scheduler/{agent_slug}/fire` — mirror of
  `whatsapp_inbound_relay`: resolve agent by slug, 404 unknown, 503 no
  machine; forward RAW body + `x-sched-timestamp` / `x-sched-signature` +
  derived `x-luna-proxy-secret` + `fly-force-instance-id` to
  `{agent.internal_url}/api/p/plugin-scheduler/fire`; on transport error wake
  via `_try_wake_agent` and retry once; return the plugin's status upstream so
  the service's retry/dead-letter machinery sees real outcomes. Timeout ~120s
  (a fire can trigger a long agent turn on a cold machine).

## Phase C — Agent-facing self-service API

`cloud/api/scheduler_agent_routes.py`, tenant-token authed (resolve agent like
`gateway_agent_routes.py`), rate-limited, **also mounted under `/proxy`**
(034.1 v0.8.0 lesson — plugins reach us through the proxy suffix):

- `POST /api/agent/scheduler/connect` → `cloud/scheduler_svc/provision.py`:
  idempotent `POST {svc}/accounts` with `account_id = agent.slug`,
  `fire_url = https://{our host}/api/webhooks/scheduler/{slug}/fire`
  (admin key, server-side only). Returns `{account_id, secret?, service_url,
  status}` (secret only when newly created/rotated). Records
  `plugin-scheduler` in `config_overrides.installed_plugins`.
- `GET /api/agent/scheduler/status` → that account's slice of `{svc}/stats`
  (trigger count, next fire, fires 24h, dead-letters).
- `DELETE /api/agent/scheduler/connect` → `DELETE {svc}/accounts/{slug}`.

Security: `account_id` is forced to the token's agent slug server-side; a
machine can only provision or delete itself. Admin key never leaves us.

## Phase D — Admin monitoring page (the left-pane page)

- `GET /api/admin/scheduler/stats` (`require_admin`) — httpx GET
  `{svc}/stats` with `x-admin-key`, ~5s timeout, ~12s cache. Same never-5xx
  contract as WhatsApp: unreachable ⇒ `{"reachable": false}`; bad key ⇒
  `{"reachable": true, "authorized": false}`; else the stats payload.
- `GET /api/admin/scheduler/instances` — per `Agent`: plugin installed?,
  account joined from `/stats.accounts[]` by slug (trigger count, next fire,
  last fire at/status, fires 24h).
- `GET /api/admin/scheduler/triggers` — proxy of the service's fleet trigger
  list (admin key): agent, name, expr (human + cron), tz, action type/target,
  enabled, next/last run — this is the "lists triggers" view.
- `cloud/ui/src/pages/admin/SchedulerPage.tsx` + nav item
  `{to: '/admin/scheduler', label: 'Scheduler', icon: Clock}` in
  `AdminLayout.tsx` `NAV_ITEMS` + route in `App.tsx`. Poll 15s
  (`RelayPage.tsx` conventions):
  - **Vitals strip**: 🟢 Online / 🔴 Offline pill, version, uptime, ticker
    lag (now − last tick; amber > 60s), DB ok/latency.
  - **Cards**: accounts (total/active), triggers (enabled/paused), fires
    (last hour / 24h, success vs failed), dead-letters (24h, red > 0).
  - **Upcoming** list: next ~20 fires fleet-wide (time, agent, trigger).
  - **Triggers table** (read-only, filter by agent).
  - **Instances table** from `/instances`.
  - Unset config ⇒ "not configured" empty state; failed poll ⇒ Offline.

## Phase E — Catalog

Supported Plugins catalog entry for `plugin-scheduler` (marketplace, not in
the default baked set until proven — 034 Phase 3 posture). Install needs no
env delta: the plugin self-provisions via Phase C (D4).

## Phase F — Tests + dojo

- Unit (`cloud/tests/`): stats proxy (unauth 403, unset config, upstream 401,
  timeout ⇒ `reachable:false`, cache TTL); connect (service mocked — right
  `account_id`/`fire_url`, idempotent re-connect, slug forced from token,
  agent A cannot touch B); fire relay (unknown slug 404, no machine 503,
  headers forwarded raw, wake-then-retry-once path, upstream status passed
  through); routes reachable under `/proxy`.
- Dojo (`tests/035-scheduler/`), against the local stack with a machine
  allowed to sleep: install plugin → settings tab shows connected with zero
  other steps → agent creates "every 2 minutes run playbook X" by chat →
  trigger listed in plugin tab AND on the admin Scheduler page → machine
  stopped → at fire time it wakes and X runs (running badge + Stop) →
  agent-prompt trigger posts a chat turn likewise → pause stops firing →
  replayed `fire_id` does not double-run → delete cleans up; admin page shows
  vitals, the trigger rows, and the fire history throughout.

## Files touched (this repo)

- `cloud/config.py`, `.env.example` — 2 settings
- `cloud/api/scheduler_routes.py` — new (admin proxy + fire relay)
- `cloud/api/scheduler_agent_routes.py` — new (self-service, + `/proxy` mount)
- `cloud/scheduler_svc/provision.py` — new
- `cloud/main.py` — register routers
- `cloud/ui/src/pages/admin/SchedulerPage.tsx` — new;
  `AdminLayout.tsx`, `App.tsx` — nav + route
- Supported Plugins catalog entry

## Order of work

1. New project bootstraps from the two companion files (service first — the
   plugin builds against its API).
2. Here, in parallel: Phases A–D against the service's API contract (mock
   upstream until it deploys).
3. Service live on Render → set the two `CLOUD_*` vars → Phase E catalog
   entry → Phase F dojo end-to-end → execution summary per devprocess §7.

## Acceptance

- Fresh hosted Luna → user installs Scheduler from the marketplace tab → asks
  their Luna "every weekday at 9am, summarize my inbox" → trigger exists on
  the service, visible in the plugin tab and the admin page → machine asleep
  at 9am → it wakes and the turn runs through the normal agent loop.
- A playbook trigger runs the playbook (indicator + Stop), and playbooks can
  themselves call the trigger tools.
- Admin left-nav Scheduler page shows the service Online with live vitals,
  the fleet trigger list, upcoming fires, and per-Luna rows; service down ⇒
  Offline within one poll; unset config ⇒ clean empty state.
- No admin action, env var, or vault form is ever needed by the user.
