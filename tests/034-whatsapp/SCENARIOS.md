# 034 — WhatsApp gateway monitoring — scenarios

Dojo-style. LLM is the test runner: drive the admin UI in a browser, verify with your own eyes.

Prereqs: `CLOUD_WHATSAPP_GATEWAY_URL` (+ `CLOUD_WHATSAPP_GATEWAY_ADMIN_KEY` for S2–S5)
set on the control plane. Without them run S1 only.

## S1 — Not configured empty state
1. Unset `CLOUD_WHATSAPP_GATEWAY_URL`, start the app, log in as admin.
2. Left nav shows a **WhatsApp** item (MessageCircle icon) after Key Registry.
3. Click it. Expect a calm "not configured" card naming the two env vars — no
   crash, no error toast, no infinite spinner.

## S2 — Live vitals
1. With both env vars set, open Admin → WhatsApp.
2. Status pill: 🟢 Online when the gateway reports `connected: true`; 🟡
   Connecting for `connecting`/`starting`/`linking`; the raw `status` string is
   shown next to the pill.
3. If `has_qr` is true, an amber "needs QR re-link" strip appears with a link to
   the gateway QR page (opens the gateway host `/qr?key=…` — verify the link
   target is the gateway, and the admin key comes from the server config, never
   from a value visible in page source before clicking).
4. Vitals show linked number (`self_jid` or —), uptime (humanized), last
   activity, memory (MB), gateway version.

## S3 — Metrics + chart
1. Cards: Users (1h / 24h / total), Messages (in+out 1h / 24h / total), Chats,
   Send budget (progress bar `sent_today` / cap — amber ≥ 80%, red at 100%),
   Media 24h breakdown, Database (ok + latency; if gateway says `db.ok:false`
   the card clearly reads "server up, DB down").
2. A 24-bucket hourly bar chart, inbound vs outbound, with a legend.
3. Freshness line "last message N m ago" from `last_message_at`.

## S4 — Offline behavior
1. Point `CLOUD_WHATSAPP_GATEWAY_URL` at a dead host, reload.
2. Pill shows 🔴 Offline within one poll (~15 s). Page keeps rendering (no
   toast/crash); metrics show —.
3. Wrong admin key → distinct "unauthorized — check the admin key" state, not
   Offline.

## S5 — Instances table
1. Table lists every agent (machine) with: name/slug, machine status, WhatsApp
   plugin installed?.
2. Agents with `plugin-whatsapp` in their installed plugins show "installed";
   others show —.
3. No secrets appear anywhere in the page or in network responses (check the
   `/api/admin/whatsapp/stats` response in devtools: no admin key echoed).

## S6 — Auth
1. Log in as a non-admin user, GET `/api/admin/whatsapp/stats` directly → 403.
2. Anonymous → 401. The `/admin/whatsapp` route redirects non-admins away
   (AdminLayout guard).
