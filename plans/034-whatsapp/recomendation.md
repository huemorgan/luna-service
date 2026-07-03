# 034 — WhatsApp Gateway Monitoring Page

## What we want

A **WhatsApp** item in the admin left pane (`NAV_ITEMS` in
`cloud/ui/src/pages/admin/AdminLayout.tsx`, e.g. with a `MessageCircle` icon).
Clicking it opens a status page for the always-on WhatsApp gateway
(`luna-wa-gateway`, a Node/Baileys service running on Render) so we can see at
a glance whether WhatsApp is up and how busy it is — without opening the
Render dashboard.

## The page

Top strip — the vitals:

- **Status pill** — 🟢 **Online** when `connected: true`, 🟡 **Connecting**
  (`status: connecting`/`starting`), 🔴 **Offline** when the fetch fails or
  `connected: false`. Show `status` verbatim next to the pill.
- **Linked number** — `self_jid`; if `has_qr: true` show a "needs QR re-link"
  warning linking to the gateway's `/qr?key=…` page.
- **Live connection** — the gateway holds exactly **one** upstream WhatsApp
  socket (Baileys); "connections" therefore = socket up/down plus **active
  chats** (`last_hour.active_chats` / `last_24h.active_chats`).
- **Uptime** (`uptime_s`), **last activity** (`last_activity_at`), **memory**
  (`rss_mb`), gateway `version`.

Metric cards:

- **Users** — `last_hour.active_users`, `last_24h.active_users`, all-time
  `totals.users` (distinct senders).
- **Messages** — in/out for the last hour (`last_hour.messages_in/out`) and
  last 24 h (`last_24h.messages_in/out`); all-time `totals.messages`.
- **Chats** — active chats per window + `totals.chats`.
- **Send budget** — `sent_today` vs `send_daily_cap` as a progress bar
  (ban-risk guard; amber ≥ 80 %, red at cap).
- **Media (24 h)** — `media_24h` kind breakdown (image/video/audio/document).
- **Database** — `db.ok` + `db.latency_ms`. If `db.ok: false` show
  "server up, DB down" distinctly (the gateway still answers).

Chart: a 24-hour bar chart from `hourly`
(`[{ hour, in, out }]`, one bucket per hour) — inbound vs outbound.

Freshness: `last_message_at` ("last message 4 m ago"). Poll the page every
~15 s; a stale/failed poll flips the pill to Offline.

## Where the info comes from

One endpoint on the gateway (already implemented, luna-whatsapp repo,
`gateway/src/index.js` + `src/stats.js`):

```
GET {WHATSAPP_GATEWAY_URL}/stats
    header  x-admin-key: {WHATSAPP_GATEWAY_ADMIN_KEY}   (or ?key=)
```

Response (abridged):

```json
{
  "status": "open", "connected": true,
  "self_jid": "9725…@s.whatsapp.net", "has_qr": false,
  "last_activity_at": "…", "uptime_s": 86400,
  "version": "0.1.0", "node": "v20.x", "rss_mb": 142,
  "sent_today": 12, "send_daily_cap": 300,
  "db": { "ok": true, "latency_ms": 9 },
  "totals":   { "messages": 5120, "chats": 41, "users": 38 },
  "last_hour":{ "messages_in": 6, "messages_out": 5, "active_chats": 3, "active_users": 3 },
  "last_24h": { "messages_in": 140, "messages_out": 120, "active_chats": 17, "active_users": 15 },
  "media_24h": { "image": 9, "audio": 2 },
  "hourly": [ { "hour": "2026-07-03T10:00:00.000Z", "in": 12, "out": 9 } ],
  "last_message_at": "2026-07-03T11:58:21.000Z"
}
```

`401 {"error":"unauthorized"}` on a bad key. There is also an unauthenticated
`GET /health` (status + `sent_today` only) usable as a cheap liveness probe.

## How to connect

The admin key must **never reach the browser** — proxy server-side, like the
existing gateway proxies (`cloud/api/gateway_proxy.py` pattern):

1. Config (`cloud/config.py` + Render env):
   - `WHATSAPP_GATEWAY_URL` — the gateway's Render URL
   - `WHATSAPP_GATEWAY_ADMIN_KEY` — its `GATEWAY_ADMIN_KEY`
   (values are in the `luna-wa-gateway` service's env on Render; ask Roy if
   missing. Unset ⇒ the page shows a "not configured" empty state, no crash.)
2. New router `cloud/api/whatsapp_routes.py`:
   `GET /api/admin/whatsapp/stats` (admin-authed like other admin routes) →
   fetches `{url}/stats` with the `x-admin-key` header, ~5 s timeout,
   short in-process cache (10–15 s) so page polling never hammers the gateway.
   Gateway unreachable ⇒ `200 {"reachable": false}` (the page renders Offline,
   not an error toast).
3. UI: `cloud/ui/src/pages/admin/WhatsAppPage.tsx`, route + nav entry in
   `AdminLayout.tsx`, reuse `InfoCard`/`ComingSoonCard` styling conventions.

## Ideas for later (don't block v1)

- Recent-chats table (needs a new gateway endpoint; not in `/stats` yet).
- Alerting: flip to Offline → notify (email/WhatsApp-to-admin).
- Watchdog/reconnect history (`whatsapp_state.watchdog`), error-rate counters.
- Multi-account support once the gateway grows beyond `account: default`.

## Source of truth

Gateway repo: `luna-whatsapp` (`gateway/` — Express + Baileys + Postgres,
deployed on Render as `luna-wa-gateway`, blueprint in its `render.yaml`).
Its plan for this feature: `plans/001-whatsapp-monitoring/PLAN.md` there.
