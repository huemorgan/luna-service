# Plan 045 execution summary

Date: 2026-07-16
Branch: `045-telegram-service-page`
Deploy state: not deployed
Commit state: uncommitted, as requested

## What was accomplished

- Added Telegram gateway configuration in `cloud/config.py` and `.env.example`:
  `CLOUD_TELEGRAM_GATEWAY_URL`,
  `CLOUD_TELEGRAM_GATEWAY_ADMIN_KEY`, and
  `CLOUD_TELEGRAM_PLUGIN_MARKETPLACE_URL`, whose confirmed default is
  `https://marketplaces.com.ai/mp/official/`.
- Added `cloud/telegram/provision.py` for external account create/read/delete
  calls, relay URL construction, supported-catalog seeding, and contract
  normalization. The adapter accepts canonical v0.2 account fields and nested
  compatibility fields, raw Telegram webhook info, canonical/flat stats, and
  derives privacy mode, group visibility, split message fallbacks, chats, and
  forwarding failures.
- Added admin monitoring in `cloud/api/telegram_routes.py`:
  `GET /api/admin/telegram/stats` and `/instances`, a shared 12-second cache,
  graceful config/network/auth states, recursive credential redaction, and a
  per-agent account join by `account_id == agent.slug`.
- Added the public relay
  `POST /api/webhooks/telegram/{agent_slug}/inbound`. It forwards exact bytes,
  `x-tg-account`, `x-tg-timestamp`, and `x-tg-signature` to
  `/api/p/plugin-telegram/inbound`, preserving the established trusted-proxy,
  Fly instance routing, wake, and one-retry behavior.
- Added tenant-token routes in `cloud/api/telegram_agent_routes.py`:
  `POST /connect`, `GET /status`, and `DELETE /connect`, plus `/proxy` aliases.
  Account IDs are always the authenticated `Agent.slug`. BotFather tokens are
  sent only in the gateway `POST /accounts` request and are never written to
  luna-service state or logs. Connect returns `account_id`, `gateway_url`,
  sanitized bot metadata, and `shared_secret` from the canonical
  `{ok, account, shared_secret}` response. `bot_already_connected` maps to 409;
  missing gateway `PUBLIC_URL` maps to a clear 503.
- Successful connect records `plugin-telegram` in
  `Agent.config_overrides["installed_plugins"]`.
- Registered all routers in `cloud/main.py`. No database schema or migration was
  added.
- Added the read-only Telegram admin UI in
  `cloud/ui/src/pages/admin/TelegramPage.tsx`, its Services navigation item, and
  `/admin/telegram` route. It polls every 15 seconds and renders gateway,
  webhook, database, fleet, hourly traffic, and per-Luna state without token
  fields.
- Made `AdminLayout.tsx` usable on narrow screens with an accessible collapsible
  navigation and responsive main padding.
- Added 21 Telegram backend tests, browser scenarios, a reusable local browser
  harness, and this execution/test record.

Verification:

- Post-contract Telegram suite: 21 passed in 3.45s.
- Post-contract Telegram + WhatsApp + Scheduler focused suite: 72 passed in
  15.77s.
- Earlier complete backend suite on this implementation: 659 passed, 1 skipped.
- Frontend production build: passed.
- Edited frontend-file lint: passed.
- Browser scenarios 1–5: passed with screenshots and DOM inspection.
- Live external scenarios 6–8: blocked/partial as recorded in
  `tests/045-telegram-service-page/TEST-REPORT.md`.

## What we discovered

- Cross-repository review confirmed the official plugin marketplace URL as
  `https://marketplaces.com.ai/mp/official/`. This matches the existing
  WhatsApp convention of a real marketplace default, so Telegram now uses that
  exact default and startup seeds the supported entry.
- The existing admin layout used a fixed 224px sidebar and left only 166px of
  content at a 390px viewport. Browser testing exposed this. The layout now
  hides the sidebar behind an accessible mobile menu and keeps the Telegram
  table's horizontal scroll local to its container.
- The clean test environment required an ad-hoc `aiosqlite` install because the
  existing test fixture uses SQLite while `cloud/pyproject.toml` does not list
  `aiosqlite` in its dev extra. No dependency file was changed for this
  pre-existing packaging gap.
- Repository-wide frontend lint already fails in unrelated files. All edited
  frontend files lint clean.

## Gateway and plugin contract alignment

Cross-repository review supplied the v0.2 response shapes. Luna-service now
consumes:

- gateway admin authentication uses `x-admin-key`, matching WhatsApp and
  Scheduler;
- `POST /accounts` accepts `{account_id, bot_token, inbound_url}` and returns
  `{ok, account, shared_secret}`;
- canonical flat `bot_id`, `bot_username`, `bot_name`,
  `can_join_groups`, `can_read_all_group_messages`, and
  `supports_inline_queries`, with nested `account.bot` compatibility;
- raw Telegram webhook fields `url`, `pending_update_count`,
  `last_error_date`, and `last_error_message`, with normalized compatibility
  aliases;
- current account metrics `messages_24h`, `chats_24h`, and
  `forward_failures`, while preferring the arriving split
  `messages_24h_in/out`;
- `GET /accounts/{id}` may return either an account directly or
  `{account: ...}`;
- `/stats` canonical `version`, `uptime_s`, `db`, `webhook`, `totals`,
  `hourly`, and `accounts`, plus retained flat compatibility;
- invalid BotFather tokens produce 400 or 422; admin auth failures produce 401
  or 403; `bot_already_connected` produces 409; gateway `PUBLIC_URL`
  misconfiguration produces 503; delete success/missing produces 200, 204, or
  404;
- the plugin inbound contract is exact raw bytes plus `x-tg-account`,
  `x-tg-timestamp`, and `x-tg-signature` at
  `/api/p/plugin-telegram/inbound`.

The relay already preserved `x-tg-account`, so the gateway forwarding change
required no relay code change. Contract fixture tests now lock these shapes.
Only live endpoint behavior remains unverified.

## Things to consider

- Run the blocked browser scenarios with a disposable BotFather token after the
  v0.2 gateway and plugin are deployed.
- Consider adding `aiosqlite` to the repository's dev dependency set in a
  separate maintenance change.
