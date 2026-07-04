# 034 WhatsApp — Status summary

**Updated:** 2026-07-05 · **From:** luna-whatsapp (gateway + plugin side)
**TL;DR: the multi-account gateway is built, tested, and LIVE. Both luna-service
phases are unblocked. Nothing on the gateway side is pending.**

## Where each piece stands

| Piece | Status | Where |
|---|---|---|
| Gateway, multi-account (003) | ✅ **live in production** | https://luna-wa-gateway.onrender.com (Render `luna-wa-gateway`, same workspace) |
| `/accounts` admin API | ✅ live, prod-verified | contract in `gateway-reply.md` (matches `multi-luna-gateway-ask.md` exactly) |
| `/stats` + `accounts[]` | ✅ live; pre-034 keys frozen | shape in `recomendation.md` + `gateway-reply.md` |
| plugin-whatsapp **v0.6.0** | ✅ published | marketplaces.com.ai official catalog — pin `>=0.6.0` |
| `default` account (Roy's number → luna-kp8e) | ⏳ migrated fine, **awaiting Roy's QR scan** | `status: linking` — your Phase-1 page showing "Connecting/needs re-link" is CORRECT |
| luna-service Phase 1 (admin monitoring page) | ⬜ **yours, unblocked** — no gateway dependency | `PLAN.md` Phase 1 |
| luna-service Phase 2 (per-instance connect flow) | ⬜ **yours, unblocked** — API is live | `PLAN.md` Phase 2 |

## What the gateway now is (one paragraph)

One Render service holding N Baileys sessions — one per account = WhatsApp
number = Luna instance — driven by a Postgres registry (`whatsapp_accounts`):
per-account HMAC secret (a tenant's secret can ONLY send through its own
number; cross-account claims 401), per-account inbound URL (envelopes signed
with that account's secret, POSTed to that Luna), per-account QR lifecycle and
daily send cap, `gateway_id` column ready for sharding. Roy's original
single-account setup survived untouched as account `default`.

## What luna-service should do next

1. **Phase 1 now**: build the admin WhatsApp page against `/stats`. One-time
   manual step: copy the gateway's `GATEWAY_ADMIN_KEY` (Render dashboard →
   luna-wa-gateway → Environment) into `CLOUD_WHATSAPP_GATEWAY_ADMIN_KEY`.
2. **Phase 2**: `POST /accounts {account_id: agent.slug, inbound_url}` →
   store returned secret as vault `plugin_whatsapp.shared_secret` + the slug
   as vault `plugin_whatsapp.account_id` (both vault writes ⇒ no machine
   restart), install plugin `>=0.6.0` from the catalog, bake/backfill the
   constant `LUNA_WHATSAPP_GATEWAY_URL`, proxy `GET /accounts/{id}/qr`
   server-side into your UI.
3. Remember: waking a stopped Fly machine on inbound is **your** side
   (gateway does direct signed POSTs, 120s tolerance, no timeout retries).

## Verification behind the "live" claim

35 gateway unit tests + 82 plugin tests green; integration matrix on an
isolated stack (legacy migration idempotence, HMAC resolution incl. rotation
and cross-account rejection, delete cleanup); dojo conversation suite through
the new gateway; production acceptance (scratch account created → QR issued →
isolation proven → deleted). Full detail: luna-whatsapp
`plans/003-whatsapp-multiluna/PLAN.md` + `tests/dojo/RESULTS.md`.

## Cross-references

- `recomendation.md` — original monitoring-page brief (Phase 1 spec).
- `multi-luna-gateway-ask.md` — your ask; accepted and shipped as specced.
- `gateway-reply.md` — accepted contract + LIVE update with API details.
- `PLAN.md` — your two-phase plan; both phases now executable.
