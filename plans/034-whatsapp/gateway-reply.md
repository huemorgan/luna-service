# Reply from luna-whatsapp — multi-Luna gateway ask: ACCEPTED

**From:** luna-whatsapp (gateway + plugin)
**Date:** 2026-07-04
**Re:** `multi-luna-gateway-ask.md` / your `PLAN.md` Phases 1–3

## Verdict

Accepted as specced. Our implementation plan is
**`plans/003-whatsapp-multiluna/PLAN.md`** in the luna-whatsapp repo
(https://github.com/huemorgan/luna-whatsapp). The API contract you proposed
lands unchanged — build Phase 2 against it:

- `POST /accounts {account_id, inbound_url, daily_cap?}` → `{account_id,
  secret, status, qr_url}`; idempotent; `account_id` = your agent slug
  (validated `^[a-z0-9][a-z0-9._-]{0,63}$`).
- `GET /accounts`, `GET /accounts/{id}` — status/connected/self_jid/has_qr/
  inbound_host/sent_today/daily_cap. Never returns secrets.
- `GET /accounts/{id}/qr?format=html|json|png` — `json`/`png` exist for your
  server-side proxy → UI embed.
- `PATCH /accounts/{id}` `{inbound_url?, daily_cap?, rotate_secret?}` —
  secret returned only when rotated. Takes effect without session restart.
- `DELETE /accounts/{id}` — logout, wipe auth dir, disable (capture history
  retained).
- `/stats` gains `accounts: [{account_id, status, connected, self_jid,
  has_qr, inbound_host, messages_24h_in, messages_24h_out, sent_today,
  daily_cap, last_seen}]`. **All existing keys are frozen** — additions only.
- Per-account HMAC secrets; a tenant secret only sends through its own
  number; per-account daily caps; existing linked number migrates as account
  `default` with zero downtime.

## Execute your plan

- **Phase 1 (monitoring page): start now.** No dependency on our work; the
  `/stats` shape your page reads will not change. Your open item #2 stands:
  copy the gateway's `GATEWAY_ADMIN_KEY` (Render → luna-wa-gateway →
  Environment) into `CLOUD_WHATSAPP_GATEWAY_ADMIN_KEY`.
- **Phase 2: build against the contract above**; flip it live when we ship
  (we'll update this folder when the admin API is deployed).

## Two contract notes for Phase 2

1. **Also inject `LUNA_WHATSAPP_ACCOUNT_ID` (= agent slug)** next to
   `LUNA_WHATSAPP_GATEWAY_URL` in your env push, and pin the catalog entry at
   **plugin-whatsapp `>=0.6.0`** (not 0.5.0+). v0.6.0 sends the account id as
   `x-wa-account` so a misconfigured secret 401s loudly instead of failing
   soft, and fixes the pyproject/manifest version drift you flagged. (v0.5.0
   still works unmodified in the meantime — the gateway resolves the account
   from the HMAC secret alone.)
2. **Waking sleeping machines is yours.** Per your ask, inbound is a direct
   signed POST to each account's `inbound_url` — no queue/relay in the
   gateway. The forwarder tolerates a slow (cold-start) response up to 120s
   but deliberately does NOT retry timeouts (double-turn risk). If a tenant
   machine can be fully stopped, ensure Fly proxy auto-start covers it, or
   front it with your relay.

## Capacity (asked in req. 7)

~60–120 MB RSS per linked Baileys session. Current Render **starter (512 MB)**
holds **3–5 accounts**; **standard (2 GB)** ≈ 15–20. The registry carries
`gateway_id` from day one; sharding = second instance + your control plane
assigning `gateway_id` at account creation. We'll flag before capacity forces
the plan bump.

## Operational note

The shared number is still **unlinked** (`status: "linking"`, `has_qr: true`)
— Roy needs to scan the QR. Until then your Phase-1 page will correctly show
Connecting/needs-relink; that's real state, not a bug.
