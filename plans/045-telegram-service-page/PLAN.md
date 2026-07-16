# 045 — Telegram service page and hosted provisioning

**Status:** EXECUTING — implementation complete; external live verification blocked
**Produces version:** none
**Companions:** `huemorgan/luna-telegram` multi-account v0.2 ·
`huemorgan/plugin-telegram` plan 001

## Execution amendment

The external Telegram gateway is being upgraded in parallel to multi-account
v0.2. Luna-service targets this admin contract:

- `POST /accounts` with `{account_id, bot_token, inbound_url}`
- `GET /accounts`
- `GET /accounts/{id}`
- `DELETE /accounts/{id}`
- `GET /stats` with `accounts[]`

`POST /accounts` returns `{ok, account, shared_secret}`. Luna-service never
persists or logs the BotFather token. It returns `shared_secret`, `gateway_url`,
`account_id`, and `bot` once to the authenticated plugin so the plugin can store
its own configuration. The public Telegram gateway and webhook are managed
externally. No database migration is planned.

The v0.2 adapter accepts canonical flat account metadata (`bot_id`,
`bot_username`, `bot_name`, capabilities, raw Telegram webhook info, and
`messages_24h`/`chats_24h`/`forward_failures`) plus nested compatibility fields.
It normalizes current flat `/stats` fields and the arriving canonical
`version`/`uptime_s`/`db`/`webhook`/`totals`/`hourly` shape. Gateway conflicts
`bot_already_connected` and missing `PUBLIC_URL` are preserved as clear tenant
409 and 503 responses.

## Context

Luna-service already has WhatsApp monitoring and Scheduler tenant-provisioning
patterns. Telegram needs the parallel hosted experience:

1. Admins can monitor Telegram gateway health, webhook state, message volume,
   and per-Luna bot/account status.
2. A tenant plugin can provision its own gateway account without receiving the
   gateway admin key or changing machine environment variables.

Telegram Bot API credentials identify a bot, not a linked personal account.
There is no QR scan, and group visibility depends on BotFather privacy mode and
admin rights.

## Decision

The admin page is read-only monitoring. Tenant setup belongs in the Telegram
plugin settings UI. The control plane brokers gateway provisioning through the
existing tenant-authenticated channel. Each Luna receives its own gateway
account, forced to `agent.slug`.

## Security and data constraints

- `CLOUD_TELEGRAM_GATEWAY_ADMIN_KEY` remains server-side.
- BotFather tokens are forwarded once to the gateway and are never persisted or
  logged by luna-service.
- Tenant authentication resolves the agent server-side; callers cannot name or
  inspect another account.
- Public relay paths resolve tenants by `agent_slug`, preserve exact request
  bytes, and forward only the Telegram account, timestamp, and signature
  headers required by the plugin contract.
- Admin responses expose bot identity and status, never bot tokens, gateway
  admin keys, or shared secrets.
- Disconnect removes only the authenticated tenant's gateway account.
- Existing data is preserved; no migration is expected.

## Scope

### Configuration

Add:

- `CLOUD_TELEGRAM_GATEWAY_URL`
- `CLOUD_TELEGRAM_GATEWAY_ADMIN_KEY`
- `CLOUD_TELEGRAM_PLUGIN_MARKETPLACE_URL`, defaulting to the confirmed official
  catalog at `https://marketplaces.com.ai/mp/official/`.

Unset configuration must produce a clean unconfigured state.

### Admin API

Create admin-authenticated routes:

- `GET /api/admin/telegram/stats`
- `GET /api/admin/telegram/instances`

Use a 12-second cache. Match WhatsApp monitoring response conventions where
possible, while representing unconfigured, unreachable, and unauthorized
gateway states without leaking credentials or throwing avoidable 5xx errors.
Instances join gateway accounts to Luna agents by
`account.account_id == agent.slug`.

### Public inbound relay

Create:

- `POST /api/webhooks/telegram/{agent_slug}/inbound`

Forward the exact raw request bytes and `x-tg-account`, `x-tg-timestamp`, and
`x-tg-signature` to the tenant's `/api/p/plugin-telegram/inbound` endpoint.
Use the established wake-and-retry pattern for sleeping tenant instances.

### Tenant API

Create tenant-token routes:

- `POST /api/agent/telegram/connect`
- `GET /api/agent/telegram/status`
- `DELETE /api/agent/telegram/connect`
- `/api/agent/telegram/proxy` aliases where the analogous service pattern
  requires them.

`POST /connect` accepts `{bot_token}`, forces `account_id` to the authenticated
agent slug, builds the public relay URL, and calls gateway `POST /accounts`.
It returns `shared_secret`, `gateway_url`, `account_id`, and bot/account metadata
once to the plugin. `GET` and `DELETE` operate only on that slug. Successful
provisioning records `plugin-telegram` in installed-plugin state.

### Provisioning helper

Add `cloud/telegram/provision.py` for gateway account create/status/delete
operations and response normalization. Keep gateway credentials out of errors
and logs.

### Admin UI

Create `cloud/ui/src/pages/admin/TelegramPage.tsx`, add a Services navigation
item and `/admin/telegram` route. Poll every 15 seconds. Show:

- gateway health, webhook status, and database health cards;
- hourly inbound/outbound chart;
- read-only per-Luna account table.

No token or secret fields may exist in the admin DOM.

### Marketplace/catalog

Add `plugin-telegram` only if this repository owns the supported-plugin catalog.
Do not invent a marketplace URL that is not already available.

## Planned files

New:

- `cloud/api/telegram_routes.py`
- `cloud/api/telegram_agent_routes.py`
- `cloud/telegram/provision.py`
- `cloud/ui/src/pages/admin/TelegramPage.tsx`
- `cloud/tests/test_telegram.py`
- `cloud/tests/test_telegram_agent.py`
- `tests/045-telegram-service-page/SCENARIOS.md`
- `tests/045-telegram-service-page/TEST-REPORT.md`
- `plans/045-telegram-service-page/execution-summary.md`

Modified as needed:

- `cloud/config.py`
- `cloud/main.py`
- `.env.example`
- the existing supported-plugin catalog, if owned here
- `cloud/ui/src/pages/admin/AdminLayout.tsx`
- `cloud/ui/src/App.tsx`

## Verification

### Backend

- Admin auth, unconfigured, unauthorized, unreachable, cache, and secret
  redaction behavior.
- Exact-byte relay, required Telegram headers, tenant lookup, wake/retry, and
  unreachable tenant behavior.
- Tenant isolation for connect/status/disconnect.
- Connect forces `agent.slug`, forwards the token without persisting/logging it,
  creates the relay URL, records `plugin-telegram`, and returns one-time plugin
  configuration.
- Status and disconnect operate only on the authenticated account.
- Existing WhatsApp and Scheduler regressions remain green.

### UI

- Telegram route and Services navigation render.
- Online/degraded/offline, webhook, and database states render.
- Hourly chart and per-Luna table render at desktop and mobile sizes.
- Admin DOM contains no token or secret fields.
- Polling refreshes every 15 seconds.

### Browser/deploy truth

Execute browser scenarios against an available local application when possible.
Record screenshots and DOM observations. Do not claim live gateway or production
verification unless the external v0.2 gateway is available and credentials are
configured. Do not deploy.

## Acceptance criteria

- [x] Plan and browser scenarios exist before source changes.
- [x] Telegram appears under Services and the admin route is read-only.
- [x] Admin monitoring handles configured and failure states without secret
      leakage.
- [x] Public inbound relay preserves exact body bytes and Telegram signature
      headers.
- [x] Tenant connect/status/disconnect are isolated by authenticated agent slug.
- [x] BotFather tokens are not persisted or logged by luna-service.
- [x] Provisioning records `plugin-telegram` without a database migration.
- [x] Targeted tests, relevant regressions, edited-file lint, and frontend build
      pass.
- [x] Browser/deploy state is reported honestly.
- [ ] Real v0.2 gateway and plugin walkthrough passes with a disposable
      BotFather token.

## Execution order

1. Write browser scenarios.
2. Mirror WhatsApp and Scheduler backend patterns.
3. Add backend tests and run targeted/regression suites.
4. Add the read-only admin UI and build/lint it.
5. Execute available browser scenarios.
6. Write the test report and execution summary.
