# 034 — WhatsApp: admin monitoring + per-instance WhatsApp (multi-Luna)

**Status:** Phase 1 EXECUTED (2026-07-04, branch `034-whatsapp`) — monitoring
page + `/api/admin/whatsapp/*` live; dojo scenarios in `tests/034-whatsapp/`.
Phase 2 blocked on the gateway multi-account API (accepted, in flight —
`gateway-reply.md`).
**Companions:** `recomendation.md` (monitoring brief from luna-whatsapp, adopted
in Phase 1) · `multi-luna-gateway-ask.md` (our blocking ask TO luna-whatsapp:
convert the gateway to multi-account — this plan's Phases 2–3 depend on it)
**Upstream repo:** https://github.com/huemorgan/luna-whatsapp (gateway
`luna-wa-gateway` on Render + `plugin-whatsapp` v0.5.0 on marketplaces.com.ai)

## Direction (revised 2026-07-04)

The gateway as shipped is **single-Luna** (one Baileys socket, one number,
inbound hardwired to one `LUNA_INBOUND_URL`). That does not fit luna-service,
which runs one Luna per user. We are asking the luna-whatsapp project to make
the gateway **multi-account: one WhatsApp number per Luna instance, per-account
HMAC secrets, a DB routing registry, and an admin API for account lifecycle**
(full contract in `multi-luna-gateway-ask.md`). This plan is the luna-service
half, built against that contract:

- **Phase 1** — admin monitoring page. Ship now; works against today's
  single-account gateway and upgrades in place when per-account `/stats` lands.
- **Phase 2** — per-instance connect flow ("Connect WhatsApp" → account +
  QR + per-agent secret + plugin install). Needs the new gateway admin API.
- **Phase 3** — fleet niceties (backfill, defaults, alerting).

## Verified state (2026-07-03/04)

- Gateway live at `https://luna-wa-gateway.onrender.com`; `/health` answers
  (currently `status: "linking"`, `has_qr: true` — needs a QR re-link);
  `/stats` 401s without the admin key, payload shape per `recomendation.md`.
- Gateway auth today: `x-admin-key` (== `GATEWAY_ADMIN_KEY`) for `/stats` +
  `/qr`; HMAC (`x-wa-timestamp` + `x-wa-signature` =
  `HMAC_SHA256(secret, "{ts}.{rawBody}")`, 300s skew) for `/send`,
  `/send-media`, `/react`, and gateway→Luna inbound. Inbound target:
  `<luna-host>/api/p/plugin-whatsapp/inbound`.
- Plugin machine config: `LUNA_WHATSAPP_GATEWAY_URL` +
  `LUNA_WHATSAPP_SHARED_SECRET` (vault key `plugin_whatsapp.shared_secret`
  preferred over env — `client.py:19-31`).
- luna-service has zero WhatsApp code. Machinery we reuse:
  - `Agent` registry (`cloud/db/models.py:70`), Fly machines, env push via
    `update_machine_env` (`cloud/runtime/fly_machines.py:443`), fleet backfill
    (`cloud/api/admin_routes.py:1513`).
  - Remote plugin install: catalog hook (`plugin_catalog_routes.py:210`) →
    `apply_gateway_env_delta` (`gateway_env_delta.py:38`) → trusted-proxy
    `POST /api/p/plugin-marketplace/install` on the machine (live-load).
  - Tenant vault: per-agent secrets belong there, not in shared env.
  - Admin UI conventions: `NAV_ITEMS` (`AdminLayout.tsx:10-17`), routes
    (`App.tsx:43-55`), polling + pills (`RelayPage.tsx:27-68`),
    `InfoCard`/`ComingSoonCard`.

---

## Phase 1 — Admin monitoring page (ship now, no gateway dependency)

### Config (`cloud/config.py`, `env_prefix="CLOUD_"`)

- `whatsapp_gateway_url` → `CLOUD_WHATSAPP_GATEWAY_URL`
- `whatsapp_gateway_admin_key` → `CLOUD_WHATSAPP_GATEWAY_ADMIN_KEY` (copy the
  gateway's `GATEWAY_ADMIN_KEY` from its Render dashboard; never regenerate)

Add to `.env.example` + the control-plane Render env. Unset ⇒ page shows a
"not configured" empty state.

### API (`cloud/api/whatsapp_routes.py`, new; prefix `/api/admin/whatsapp`, all `require_admin`)

- `GET /stats` — httpx GET `{url}/stats` with `x-admin-key`, ~5s timeout,
  ~12s in-process cache (UI polls at 15s). Unreachable ⇒
  `200 {"reachable": false}`; bad key ⇒ `{"reachable": true, "authorized":
  false}`; else `{"reachable": true, "authorized": true, "stats": {...}}`.
  Never a 5xx; admin key never reaches the browser.
- `GET /instances` — per `Agent`: name/slug/status, `plugin-whatsapp`
  installed? (`config_overrides.installed_plugins`), env provisioned?
  (plan-029 env manifest, cached), and — once the multi-account gateway ships —
  joined with `/stats.accounts` by `account_id == agent.slug` to show each
  instance's number, link status, and 24h volume. Until then: readiness only.

### UI (`cloud/ui/src/pages/admin/WhatsAppPage.tsx`, new)

Nav `{to: '/admin/whatsapp', label: 'WhatsApp', icon: MessageCircle}` +
route. Poll every 15s; failed poll ⇒ Offline pill.

- **Vitals**: 🟢 Online / 🟡 Connecting (`connecting|starting|linking`) /
  🔴 Offline; `self_jid`; **"needs QR re-link" warning when `has_qr`** (live
  state today) linking to the gateway QR; uptime, last activity, rss, version.
- **Cards**: Users / Messages (in+out, hour & 24h, totals) / Chats / Send
  budget (`sent_today` vs cap, amber ≥80%) / Media 24h / Database
  (`db.ok` + latency, distinct "server up, DB down" state).
- **24h in/out bar chart** from `hourly`; freshness from `last_message_at`.
- **Instances table** from `/instances` — becomes the per-account fleet view
  (number, status, volume per Luna) when the gateway upgrade lands.

**Acceptance:** real numbers with key configured; QR warning shows today;
unset config ⇒ clean empty state; gateway down ⇒ Offline within one poll.

---

## Phase 2 — Per-instance connect flow (needs the multi-account gateway API)

Contract we consume (see `multi-luna-gateway-ask.md`): `POST /accounts`
`{account_id, inbound_url}` → per-account secret; `GET /accounts`;
`GET /accounts/{id}/qr`; `PATCH` (inbound_url / secret rotate); `DELETE`;
per-account HMAC secrets and daily caps; `/stats.accounts[]`.

### The "Connect WhatsApp" flow (one click + one QR scan)

1. Trigger: user installs `plugin-whatsapp` (Supported Plugins catalog entry —
   add it, marketplace v0.5.0+, **not** in the default baked set), or an
   explicit Connect button (admin: instances table row action; user-facing
   surface can come later).
2. Control plane (`cloud/api/whatsapp_routes.py` + a small
   `cloud/whatsapp/provision.py`) — **restart-free by design** (an
   `update_machine_env` push recreates the Fly machine; avoid it):
   - `LUNA_WHATSAPP_GATEWAY_URL` is fleet-constant → bake it into the default
     image env (`DEFAULT_IMAGE_CONFIG["env"]` / Defaults → Env) so every
     machine has it from creation; one-time backfill for older machines. No
     install-time env push at all.
   - `POST {gateway}/accounts` with `account_id = agent.slug`,
     `inbound_url = https://{agent host}/api/p/plugin-whatsapp/inbound`
     (admin-key authed, idempotent).
   - Store the returned per-account secret in **that tenant's vault** as
     `plugin_whatsapp.shared_secret` (the plugin already prefers vault over
     env — runtime write over the trusted proxy, no restart). Never shared
     across tenants, never in fleet-wide env.
   - Account id delivery: vault/settings too (needs the v0.6.0 plugin to read
     it from vault as well as env — asked in `gateway-reply.md` follow-up,
     open item 5). Env fallback stays for backfill.
   - Install the plugin (existing catalog hook — live-load, restart-free).
   - Surface the per-account QR (`GET /accounts/{id}/qr` proxied server-side)
     in the admin UI / instance page; user scans with their phone; linked.
3. Machine moves/recreates ⇒ `PATCH /accounts/{id}` with the new inbound URL —
   hook this into the same places that already handle machine recreation
   (image migrate / env backfill paths). Uninstall ⇒ `DELETE /accounts/{id}`.

### Why this shape

- Per-agent secret in the tenant vault = a leaked tenant secret only risks
  that tenant's number (the shared-secret fleet-push idea from the v1 plan is
  dead).
- The gateway admin key stays only on the control plane (it controls QR =
  number takeover).
- Everything reuses existing rails: catalog install hook, trusted-proxy
  channel, vault write, `update_machine_env`.

**Acceptance:** two different agents each connect their own number end-to-end
from our UI (no Render dashboard, no manual env), each receives inbound only
for their number and replies through it; monitoring shows both accounts;
uninstall cleans up the account.

## Phase 3 — Fleet polish (after 2)

- Backfill/reconcile job: gateway accounts ⇄ agents drift report (+ dry-run
  fix) alongside the plan-029 backfill.
- Offline/unlinked alerting from the monitoring poll (email/notify admin).
- Optionally promote `plugin-whatsapp` into the default baked plugin set
  (plan-032 Defaults → rebake) once the connect flow is proven — instances
  would ship WhatsApp-ready, connecting on first QR scan.

## Files touched (Phases 1–2)

- `cloud/config.py`, `.env.example` — 2 settings.
- `cloud/api/whatsapp_routes.py` — new (stats proxy, instances, connect/QR,
  account lifecycle calls). `cloud/main.py` — register router.
- `cloud/whatsapp/provision.py` — new (account provision + vault write).
- `cloud/api/gateway_env_delta.py` — push `LUNA_WHATSAPP_GATEWAY_URL` on
  install; trigger account provisioning for `plugin-whatsapp`.
- Catalog entry for `plugin-whatsapp`.
- `cloud/ui/src/pages/admin/WhatsAppPage.tsx` — new; `AdminLayout.tsx`,
  `App.tsx` — nav/route.

## Tests

- Stats proxy: unauth ⇒ 403; unset config; gateway 401; timeout ⇒
  `reachable:false`; cache TTL (one upstream call per burst).
- Connect flow (gateway mocked): account created with right
  `account_id`/`inbound_url`; secret lands in the right tenant vault; env push
  contains only the URL var; idempotent re-connect; PATCH on machine
  recreation; DELETE on uninstall.
- UI pill mapping incl. `linking` ⇒ Connecting + QR warning.

## Open items

1. **Blocking:** luna-whatsapp must accept + execute
   `multi-luna-gateway-ask.md` (gateway multi-account + admin API). Phase 1
   does not wait on it; Phase 2 does.
2. Copy `GATEWAY_ADMIN_KEY` into the control-plane env
   (`CLOUD_WHATSAPP_GATEWAY_ADMIN_KEY`). One-time manual.
3. The live gateway needs a QR re-link right now (`has_qr: true`).
4. Upstream nits to flag with the ask: `pyproject.toml` 0.4.0 vs manifest
   0.5.0 version drift in plugin-whatsapp (their reply says v0.6.0 fixes it).
5. Follow-up ask for plugin v0.6.0: read the account id from the vault
   (e.g. `plugin_whatsapp.account_id`) with `LUNA_WHATSAPP_ACCOUNT_ID` as env
   fallback — lets our connect flow stay restart-free (vault writes only).
6. Production env: set `CLOUD_WHATSAPP_GATEWAY_URL` +
   `CLOUD_WHATSAPP_GATEWAY_ADMIN_KEY` on the luna-service Render service
   (key from luna-wa-gateway → Environment). Until then the page shows
   "not configured" / "check the admin key".
