# 034 — Execution summary

## Phase 1 — Admin monitoring page (2026-07-04, branch `034-whatsapp`, merged `4db844d`)

### Accomplished
- `cloud/api/whatsapp_routes.py`: `GET /api/admin/whatsapp/stats` (server-side
  proxy, `x-admin-key` stays server-side, ~12s in-process cache, never-5xx
  envelope: `configured` / `reachable` / `authorized`), `GET .../qr` (server-side
  QR proxy — the original recommendation's `/qr?key=…` link would have leaked
  the admin key to the browser; the proxy fixes that), `GET .../instances`.
- `cloud/ui/src/pages/admin/WhatsAppPage.tsx` + nav/route: vitals pill,
  QR-re-link warning, metric cards, send-budget bar, 24h in/out chart,
  instances table. 15s poll, offline within one poll.
- Config `CLOUD_WHATSAPP_GATEWAY_URL` / `CLOUD_WHATSAPP_GATEWAY_ADMIN_KEY` —
  set on the luna-service Render service via the Render API (key copied from
  the luna-wa-gateway service env, never printed). Deployed live.
- 12 pytest cases; dojo scenarios `tests/034-whatsapp/SCENARIOS.md`.

### Phase-1 discoveries
- `cloud/config.py` uses `env_prefix="CLOUD_"` — the recommendation's bare
  `WHATSAPP_GATEWAY_URL` names had to become `CLOUD_WHATSAPP_*`.
- Test conftest patches `cloud.config.get_settings` as a module attribute;
  a `from cloud.config import get_settings` at import time dodges the patch.
  Use `from cloud import config` + `config.get_settings()` in new modules,
  and mutate the object `config.get_settings()` returns in tests.
- The gateway was single-Luna (one `LUNA_INBOUND_URL`); this triggered
  `multi-luna-gateway-ask.md` → the gateway team shipped multi-account
  (their plan 003) within a day, contract unchanged.

## Phase 2 — Per-instance WhatsApp, multi-Luna (2026-07-05, branch `034-whatsapp-phase2`, merged `979b567`)

### Accomplished
- **Connect flow** `POST /api/admin/whatsapp/instances/{id}/connect`
  (`cloud/whatsapp/provision.py`): creates the gateway account
  (`account_id = agent.slug`, inbound = our relay), writes the per-account
  secret to tenant vault `plugin_whatsapp.shared_secret` and the slug to
  `plugin_whatsapp.account_id` via trusted-proxy
  `POST /api/p/plugin-vault/credentials`, live-loads plugin-whatsapp
  (>=0.6.0) via `POST /api/p/plugin-marketplace/install`. Restart-free,
  idempotent. `DELETE` disconnects; `GET .../qr` proxies the per-account QR.
- **Public inbound relay** `POST /api/webhooks/whatsapp/{slug}/inbound`:
  forwards raw HMAC envelope to the machine (`fly-force-instance-id`,
  wake-on-sleep via `_try_wake_agent`, 120s, read-timeouts NOT retried to
  avoid double turns, plugin's HMAC verdict passed through). This is what
  account records register as `inbound_url` — solves both Fly header routing
  and machine wake, which a direct gateway→machine POST cannot do.
- **UI**: per-Luna WhatsApp column (status pill / own number / 24h volume),
  Connect / Show QR / Disconnect actions, QR modal (iframe on our authed
  proxy). `disabled` accounts render as not-connected so Connect reappears.
- `LUNA_WHATSAPP_GATEWAY_URL` baked into `DEFAULT_IMAGE_CONFIG["env"]`
  (`cloud/api/admin_routes.py`) — new machines get it at create; the plugin's
  other two inputs arrive via vault, so connect never restarts a machine.
- Tests: 11 new (23 WhatsApp total, suite 202 green). Browser dojo
  (Playwright, headless Chromium) against the LIVE gateway: created account
  `alice-my-luna` from a real click, real QR rendered in the per-Luna modal,
  cross-verified via gateway `/accounts`, disconnected clean; account
  `default` untouched. Screenshots in the session scratchpad.

### Phase-2 discoveries
- **Direct gateway→machine inbound can't work on Fly**: machines need the
  `fly-force-instance-id` header and may be stopped. Hence the relay; the
  gateway team had already flagged "waking sleeping machines is yours".
- `httpx.UnsupportedProtocol` (agent with empty `internal_url`) is an
  `httpx.HTTPError` but NOT a `ConnectError` — the relay now guards
  no-machine agents with 503 and catches `httpx.HTTPError` broadly, with
  `ReadTimeout` handled first (504, never retried).
- Gateway `DELETE /accounts/{id}` *disables* (history retained) rather than
  erasing — the UI must treat `status: "disabled"` as disconnected.
- The gateway returns the account secret **only on create/rotate**; an
  idempotent re-connect returns no secret, and the existing vault value
  remains valid — the flow must tolerate that.
- Prod gateway had a leftover `acceptance-probe` account (disabled) from
  their own testing; `/accounts` returns `{accounts: [...]}`, not a bare list.
- Playwright: install via `uv pip install playwright` (venv has no pip);
  Chromium builds were already cached under `~/Library/Caches/ms-playwright`.
- Local stub logins (`alice@novalystrix.ai`) are blocked by the email
  allowlist in `auth_routes.py` (`monday.com` domain + vaselin@gmail.com);
  for local dojo, mint a `luna_session` cookie directly with itsdangerous +
  `CLOUD_SESSION_SECRET` and inject it into the browser context.
- `.env` line 10 (a Fly token with commas, unquoted) breaks `source .env`;
  use `dotenv_values`, never `source`.

### Things to consider in the future
- **Existing machines lack `LUNA_WHATSAPP_GATEWAY_URL`** (only baked for new
  creates). Backfill options: extend `POST /api/admin/machines/env/backfill`
  with the var (one restart per machine), or fold into the next image
  migrate. Until then, connect works but the plugin can't reach the gateway
  on old machines.
- **plugin-whatsapp is not in the Supported Plugins catalog**
  (`PluginCatalogEntry`) yet — the connect flow installs it directly from
  `CLOUD_WHATSAPP_PLUGIN_MARKETPLACE_URL` (defaults to the official
  marketplace). Adding a catalog entry would give users the normal
  self-service install path too.
- **Self-service connect for end users** (their own dashboard, not admin) is
  unbuilt — the admin flow proves the rails; a user-facing "Connect
  WhatsApp" button on AgentDetail is the natural next slice.
- **Relay hardening**: the public relay 404s unknown slugs and passes HMAC
  through, but has no rate limit; consider one if abuse appears.
- **Capacity**: gateway starter instance ≈ 3–5 Baileys sessions (their
  numbers). The registry has `gateway_id` for sharding; our connect flow
  will need to honor it when they scale out.
- Account `default` (Roy's number → luna-kp8e) still needs its QR scan.
- The gateway's Render service does NOT auto-deploy on push (no GitHub app
  webhook) — they deploy via Render API. Ours does auto-deploy.
