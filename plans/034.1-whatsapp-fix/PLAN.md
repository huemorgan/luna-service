# 034.1 — WhatsApp connect belongs to the plugin, not the admin UI

**Status:** PLAN (not yet executed)
**Supersedes:** the admin-side connect UX from 034 Phase 2 (the machinery
stays; the admin UI actions and admin-only trigger die).

## The problem (verified by a real user flow)

A user installed plugin-whatsapp from inside their Luna's marketplace tab and
got a dead plugin: "Not configured — set LUNA_WHATSAPP_GATEWAY_URL". The 034
design put Connect on the luna-service admin page — but the person who wants
WhatsApp is the Luna's *user*, inside their Luna. Provisioning-from-admin was
the wrong altitude. Installing the plugin must be the whole setup.

## Target UX (the entire flow, user's point of view)

1. In your Luna: Marketplace → install **WhatsApp**.
2. Open the plugin's settings tab (or it opens after install): a QR is
   already waiting, with link status.
3. Scan with your phone. Done — your Luna is on WhatsApp.

No luna-service admin visit. No env vars. Nothing to configure.

## How: the machine self-provisions through its existing trusted channel

Every hosted machine already holds `LUNA_GATEWAY_URL` + `LUNA_GATEWAY_TOKEN`
(the `lsv1-` tenant token) and the control plane already exposes agent-facing,
token-authed routes (`cloud/api/gateway_agent_routes.py`, pattern:
`token_svc.verify_token` → agent). We add WhatsApp self-service on that rail.
The gateway admin key NEVER reaches the machine — the control plane stays the
only holder; the machine just asks it.

### 1. Control plane: agent-facing self-service API (new, `cloud/api/whatsapp_agent_routes.py`)

All routes authed by the tenant token (resolve `agent` like
`gateway_agent_routes.py:54`); rate-limited per agent (connect is not a hot
path).

- `POST /api/agent/whatsapp/connect` → runs the existing
  `provision.connect_agent` logic for THIS agent minus the vault push (the
  caller IS the machine): creates/asserts the gateway account
  (`account_id = agent.slug`, inbound = the 034 relay), and returns
  `{account_id, secret?, gateway_url, status}` directly in the response body
  (secret present only when newly created/rotated — gateway semantics).
  Records `plugin-whatsapp` in `config_overrides.installed_plugins` so the
  admin monitoring table stays truthful.
- `GET /api/agent/whatsapp/qr?format=html|png` → proxies the per-account QR
  (`{gw}/accounts/{slug}/qr`) with the admin key, server-side.
- `GET /api/agent/whatsapp/status` → that account's slice of `/stats`
  (status/connected/self_jid/has_qr/sent_today/daily_cap).
- `DELETE /api/agent/whatsapp/connect` → gateway `DELETE /accounts/{slug}`.

### 2. Plugin v0.7.0 (luna-whatsapp repo — file the ask as
`plans/034.1-whatsapp-fix/plugin-ask.md` there, or hand this section over)

- **Auto-provision on first need**: when config is absent (no vault
  `plugin_whatsapp.shared_secret`), and `LUNA_GATEWAY_URL` +
  `LUNA_GATEWAY_TOKEN` are present (= hosted Luna), call
  `POST {LUNA_GATEWAY_URL}/api/agent/whatsapp/connect`; store the returned
  `secret`, `account_id`, and `gateway_url` in the vault
  (`plugin_whatsapp.shared_secret` / `.account_id` / `.gateway_url`).
  Trigger points: `on_load` (best-effort, silent) and the settings tab's
  "Connect" button (explicit, surfaces errors).
- **Read gateway_url vault-first too** (like secret/account id in v0.6.0) —
  kills the `LUNA_WHATSAPP_GATEWAY_URL` env dependency entirely: no baked
  env, no fleet backfills, ever.
- **Settings tab = the QR page**: replace today's admin-key-dependent QR
  proxy with `GET {LUNA_GATEWAY_URL}/api/agent/whatsapp/qr` (tenant token) —
  render QR + link status + linked number + sent-today. The
  `LUNA_WHATSAPP_GATEWAY_ADMIN_KEY` plugin env var dies.
- **OSS/self-hosted fallback unchanged**: no gateway token → show today's
  manual-env instructions.

### 3. luna-service: delete the admin provisioning UI

- `WhatsAppPage.tsx`: remove Connect / Disconnect / "Connect another Luna"
  picker / QR modal. The page becomes **monitoring only**: gateway health
  strip, metric cards, chart, and a read-only per-Luna table (status pill,
  number, 24h volume, sent/cap) fed by `/stats.accounts[]` — which now
  reflects accounts created by the plugins themselves.
- Delete admin routes `POST/DELETE /instances/{id}/connect` and
  `GET /instances/{id}/qr`; `cloud/whatsapp/provision.py` stays (the
  agent-facing routes call it). The inbound relay (034) is untouched — it is
  transport, not UX.
- Keep `POST /env/backfill` until v0.7.0 (vault-first gateway_url) is the
  fleet floor, then delete it and the baked env var.

## Security notes

- The tenant token only lets a machine provision **its own** account
  (account_id forced to the token's agent slug server-side — the machine
  cannot name another account).
- Per-account secret is returned once over TLS to the machine that owns it —
  same trust level as the vault write in 034, one less hop.
- Gateway admin key: control plane only, unchanged.

## Migration / cleanup

- Accounts already created via the admin flow keep working (same account_id
  convention, same vault keys).
- Remove from 034: admin connect UI + routes (above). Update
  `tests/034-whatsapp-phase2/SCENARIOS.md` note pointing here.
- New dojo scenarios (`tests/034.1-whatsapp-fix/`): install plugin inside a
  Luna → settings tab shows QR with zero other steps; scan → linked; admin
  page shows the row appear (read-only); OSS Luna without token still shows
  manual instructions; a tenant token cannot connect/QR another slug.

## Order of work

1. Control plane agent-facing routes + tests (can ship immediately; harmless
   while no plugin calls them).
2. Plugin ask to luna-whatsapp → v0.7.0 published.
3. Delete admin connect UI/routes once v0.7.0 is confirmed installing clean.
4. Execution summary per devprocess §7.

## Acceptance

Fresh hosted Luna → user installs WhatsApp from the marketplace tab → opens
plugin settings → scans the QR shown there → sends a WhatsApp message →
their Luna answers. At no point does anyone open luna-service admin, set an
env var, or touch a vault form.
