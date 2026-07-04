# 034.1 — plugin-driven WhatsApp connect — scenarios

Dojo-style, real browser + API probes. Gateway is LIVE multi-account.

## S1 — Machine self-provisions (API, the core)
1. With a valid tenant token: `POST {base}/api/agent/whatsapp/connect`
   (Bearer) → 200 `{account_id == that agent's slug, secret, gateway_url,
   status}`. The caller cannot choose the account id.
2. Repeat the call → 200, same account_id, NO secret (idempotent re-connect).
3. Gateway `GET /accounts` lists the account with the relay inbound URL.
4. `GET {base}/api/agent/whatsapp/qr` (Bearer) → the account's QR HTML.
5. `GET {base}/api/agent/whatsapp/status` (Bearer) → that account's slice.
6. No token / bad token → 401. A token for agent A never returns agent B's
   account or QR.

## S2 — Admin page is monitoring-only (browser)
1. Admin → WhatsApp: NO Connect button, NO picker, NO QR modal, NO
   Disconnect — anywhere in the DOM.
2. The instances table still shows per-Luna rows (status pill, 24h msgs,
   sent/cap) for accounts that exist on the gateway.
3. Gateway health strip unchanged.

## S3 — Env residue gone
1. `DEFAULT_IMAGE_CONFIG["env"]` no longer contains
   `LUNA_WHATSAPP_GATEWAY_URL`.
2. `POST /api/admin/whatsapp/env/backfill` → 404 (route deleted).
3. `POST/DELETE /api/admin/whatsapp/instances/{id}/connect` and
   `GET .../qr` → 404/405 (routes deleted).

## S4 — Disconnect from the machine
1. `DELETE {base}/api/agent/whatsapp/connect` (Bearer) → account disabled on
   the gateway; row leaves the admin table.

## S5 — Inbound relay untouched
1. `POST {base}/api/webhooks/whatsapp/{slug}/inbound` unknown slug → 404;
   HMAC headers pass through to the machine (pytest-covered).
