# Ask to the luna-whatsapp project — plugin v0.7.0: install IS the setup

**From:** luna-service · **Date:** 2026-07-05
**Context:** `../034.1-whatsapp-fix/PLAN.md` (this folder, luna-service repo)
**Compatibility:** NONE required. No users. Delete freely; v0.7.0 replaces
v0.6.0 outright — no fallback ordering, no deprecation period.

## Goal

A user installs plugin-whatsapp from their Luna's marketplace tab, opens the
plugin's settings tab, and a QR is waiting. Scan → their Luna is on WhatsApp.
Zero env vars, zero vault forms, zero visits to luna-service admin.

## What the control plane gives you (live when you start; token-authed)

Base URL and token are already on every hosted machine:
`LUNA_GATEWAY_URL` + `LUNA_GATEWAY_TOKEN` (`lsv1-…`). Send the token as
`Authorization: Bearer {LUNA_GATEWAY_TOKEN}`.

```
POST {LUNA_GATEWAY_URL}/api/agent/whatsapp/connect
  → 200 {account_id, secret?, gateway_url, status}
    - account_id is ALWAYS the machine's own agent slug (server-enforced;
      you cannot and need not choose it)
    - secret present only on first create (or rotation) — store it then;
      on an idempotent re-connect it is absent and your stored one is valid
    - gateway_url = the wa-gateway base (store it; do not read env for it)
  → 503 gateway not configured on the control plane
  → 401 bad/missing token (self-hosted Luna — see OSS fallback)

GET {LUNA_GATEWAY_URL}/api/agent/whatsapp/qr?format=html|png
  → this machine's own account QR, proxied server-side

GET {LUNA_GATEWAY_URL}/api/agent/whatsapp/status
  → {status, connected, self_jid, has_qr, sent_today, daily_cap,
     messages_24h_in, messages_24h_out}

DELETE {LUNA_GATEWAY_URL}/api/agent/whatsapp/connect
  → unlink + disable this machine's account
```

Inbound stays exactly as in v0.6.0: the gateway POSTs the HMAC-signed
envelope to the account's registered inbound URL (the control-plane relay);
your `/inbound` route and HMAC verification are unchanged.

## Plugin changes (v0.7.0)

1. **Auto-provision.** When the vault has no `plugin_whatsapp.shared_secret`
   AND `LUNA_GATEWAY_URL`/`LUNA_GATEWAY_TOKEN` are present:
   call `POST …/connect`, then store in the vault:
   - `plugin_whatsapp.shared_secret` ← `secret`
   - `plugin_whatsapp.account_id`   ← `account_id`
   - `plugin_whatsapp.gateway_url`  ← `gateway_url`
   Trigger on `on_load` (best-effort, silent on failure) and from the
   settings tab (explicit button, surfaces errors). Idempotent by design.
2. **Vault-first everything.** Add `plugin_whatsapp.gateway_url` (vault →
   env fallback), same pattern as secret/account_id in v0.6.0. This deletes
   the hosted dependency on `LUNA_WHATSAPP_GATEWAY_URL` env.
3. **Settings tab = QR + status page.** Render, via the control-plane
   endpoints above (NOT the gateway admin key):
   - link status pill (`status`/`connected`/`self_jid`)
   - the QR (`GET …/qr`, self-refresh until linked)
   - sent today / daily cap
   - a Disconnect button (`DELETE …/connect`)
4. **Deletions** (no compatibility):
   - `LUNA_WHATSAPP_GATEWAY_ADMIN_KEY` env + the admin-key QR proxy route
     (`GET /api/p/plugin-whatsapp/qr` in its current form — reimplement on
     the token endpoint or drop it; the settings tab is the surface)
   - any code path that assumes a single/global account
5. **OSS/self-hosted fallback** (no gateway token): keep the manual config
   path — `LUNA_WHATSAPP_GATEWAY_URL` + secret/account id via env or vault —
   and say so in the settings tab. Nothing else.
6. Bump BOTH manifests to `0.7.0` (pyproject.toml drifted at 0.4.0 before
   0.6.0 fixed it — keep them locked) and publish to the official
   marketplace.

## Tests we care about

- Fresh install on a hosted Luna (token present, empty vault): `on_load`
  provisions; settings tab shows a QR with no other action.
- Re-load after provisioning: no second account call needed (vault hit);
  if called anyway, absent `secret` in the response leaves the vault intact.
- Self-hosted (no token): no calls to LUNA_GATEWAY_URL; manual instructions
  shown; env-configured setup still works.
- The settings tab never contains the gateway admin key or the tenant
  token in page source.

## Acceptance (end to end)

Marketplace install → settings tab → scan QR → send a WhatsApp message from
a phone → the Luna replies. Nothing else was touched by anyone.
