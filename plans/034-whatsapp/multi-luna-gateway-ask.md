# Ask to the luna-whatsapp project — the gateway must serve MULTIPLE Lunas

**From:** luna-service (the hosted multi-tenant product)
**Date:** 2026-07-04
**Priority:** blocking — luna-service cannot roll WhatsApp out to its fleet on
the current design.

## The problem

The gateway was built single-Luna: one Baileys socket, one WhatsApp number,
and inbound forwarding hardwired to a **single** `LUNA_INBOUND_URL` env var
(`gateway/src/config.js:24`, `src/inbound.js`). luna-service provisions one
Luna instance **per user** (Fly machine per `Agent`). With today's gateway,
every instance can send through the shared number but only ONE instance can
ever receive — that is not a connector service, it's a personal bridge.

This was always the plan eventually — your own `vision/roadmap.md` Phase 3
describes multi-tenant sessions — but it needs to happen **now**, not later.

## What we need you to do

Go over everything — `gateway/` (config, wa.js session handling, inbound
forwarding, db schema, stats), `plugin-whatsapp/`, the vision docs, and both
monitoring plans (`plans/001-whatsapp-monitoring/` there,
`plans/034-whatsapp/` here) — and produce a plan (in your `plans/`, next
number) that converts the gateway from single-Luna to **multi-account,
multi-Luna**, then execute it. Requirements below; the API shape is a
proposal — improve it if you see better, but keep the requirements.

## Requirements

1. **One account = one WhatsApp number = one Luna instance.** N Baileys
   sessions in the gateway, each with its own auth dir on the persistent disk
   (`/data/wa-auth/<account_id>/`), its own QR/link lifecycle, its own daily
   send cap. The `account` column already on every table becomes real;
   `whatsapp_state` drops its `CHECK id=1` singleton and becomes one row per
   account.
2. **Per-account routing registry (DB, not env).** Each account row stores:
   `account_id`, `inbound_url` (that Luna's
   `https://<host>/api/p/plugin-whatsapp/inbound`), `secret` (per-account HMAC
   secret), `status`, `self_jid`. Inbound for a session is signed with **that
   account's** secret and POSTed to **that account's** `inbound_url`.
   `LUNA_INBOUND_URL` / `WA_SHARED_SECRET` remain only as a legacy fallback
   for the existing linked account (zero-downtime migration).
3. **Per-account secrets, not one shared secret.** A tenant's secret must only
   authorize sending through *their* number. Send/react endpoints resolve the
   account from the HMAC secret used (or an explicit `x-wa-account` header —
   your call), and the per-account daily cap applies.
4. **Admin API for account lifecycle** (admin-key gated, this is what
   luna-service's control plane will call):
   - `POST /accounts` `{account_id, inbound_url}` → creates the session slot,
     generates + returns the per-account secret, starts linking. Idempotent.
   - `GET /accounts` → list with per-account `status/connected/self_jid/has_qr/sent_today`.
   - `GET /accounts/{id}/qr` → QR (HTML page and/or PNG/JSON) for that account.
   - `PATCH /accounts/{id}` → update `inbound_url` (machine moved) / rotate secret.
   - `DELETE /accounts/{id}` → logout, drop session + auth dir.
5. **`/stats` gains a per-account breakdown** (`accounts: [{account_id,
   status, connected, self_jid, has_qr, messages_24h_in/out, sent_today,
   cap}]`) on top of the existing global totals. Also add the inbound **host**
   per account so our monitoring page can show which Luna each number feeds.
6. **Plugin side:** audit `plugin-whatsapp` for multi-account fit. It should
   already be close (it has its own secret + gateway URL per Luna); confirm
   sends are attributed to the right account, and bump/publish a new version
   if anything changes.
7. **Capacity honesty:** state in the plan how many concurrent Baileys
   sessions one Render `starter` instance realistically holds (memory per
   socket), and what the sharding story is when we outgrow it (`gateway_id`
   column per your roadmap is fine to defer — but design the registry so it
   slots in).
8. **Don't break the live account.** The currently linked number keeps working
   through the migration (it becomes account `default`).

## What luna-service will do on our side (so you know the consumer)

Our control plane will: call `POST /accounts` when a user clicks "Connect
WhatsApp" (account_id = agent slug, inbound_url = that machine's public host),
store the returned per-account secret in that tenant's vault
(`plugin_whatsapp.shared_secret`), proxy the per-account QR into our UI,
install `plugin-whatsapp` on the machine, and inject
`LUNA_WHATSAPP_GATEWAY_URL`. Our admin monitoring page will consume the
per-account `/stats`. Our updated plan: `luna-service/plans/034-whatsapp/PLAN.md`.

## Acceptance (from our side)

- Two different Luna instances each link their **own** number via their own QR
  and each receives inbound only for their number, replies through their own
  account, with per-account caps and secrets.
- A compromised tenant secret cannot send through anyone else's number.
- The pre-existing linked number keeps working untouched.
- `/stats` shows the per-account table; account lifecycle is fully driveable
  via the admin API (no Render dashboard edits, no env changes, no redeploys
  to add a Luna).
