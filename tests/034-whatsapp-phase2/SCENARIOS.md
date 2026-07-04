# 034 Phase 2 — per-instance WhatsApp connect — scenarios

Dojo-style, real browser. Gateway is the LIVE multi-account service; never
touch account `default` (Roy's number).

## S1 — Instances table shows per-Luna WhatsApp state
1. Admin → WhatsApp. Instances table has columns: Agent, Machine, Plugin,
   WhatsApp, 24h msgs, action.
2. The `default` account does NOT hijack any agent row (no agent slug =
   `default`); unconnected agents show — and a **Connect** button.

## S2 — Connect a Luna (the core flow)
1. Click **Connect** on a test agent row.
2. Within a few seconds the row flips to a WhatsApp status pill (`linking` /
   needs QR) and the action becomes **Show QR**.
3. No machine restart happened (docker/fly machine uptime unchanged) — the
   secret + account id went in via vault writes.
4. Gateway-side: `GET /accounts` (admin key) lists the new account with
   `account_id == agent.slug` and our relay inbound URL.

## S3 — Per-Luna QR (the "not one QR" ask)
1. Click **Show QR** on the connected test agent → modal opens with THAT
   account's QR (served via our authed proxy, admin key never in page source).
2. The service-level banner QR (account `default`) is a different account —
   verify the modal title names the agent slug.

## S4 — Disconnect
1. Disconnect the test agent → row returns to Connect state; gateway
   `GET /accounts` no longer lists it. Account `default` untouched.

## S5 — Inbound relay (public path)
1. `POST {base}/api/webhooks/whatsapp/{slug}/inbound` with a bogus signature →
   the relay forwards to the Luna and returns the plugin's 401/503 (NOT a
   control-plane 401 — proves pass-through), unknown slug → 404.

## S6 — No secrets in the browser
1. Network tab: /instances and /stats responses contain no secret, no admin
   key; QR iframe URL is our proxy path.
