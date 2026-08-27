# Phase 4 — execution summary

## What shipped

Pushed phases 1–3 plus plan docs to `huemorgan/luna-service` main:
`c7a3609` (phase 1: schema + ingress + wake/wait), `44b0725` (phase 2: mint API),
`71839a3` (phase 3: admin API + admin UI), `356aa42` (plan docs). Render
autodeployed; the new code answered production probes ~80 s after push.
Migration 0016 (`webhook_endpoints` table + `relay_deliveries.target_path`)
applied on boot — proven by the ingress route answering from the new table.

## Production verification (what passed)

- **Ingress live**: `GET https://luna.com.ai/api/webhooks/hooks/probe/probe` →
  `404 {"detail":"Unknown hook"}` — the route exists (not the SPA catch-all) and
  reads the `webhook_endpoints` table, so migration 0016 applied.
- **Mint API live and gated**: `POST /api/agent/webhooks/hooks` without a device
  token → 401.
- **Admin API live and gated**: `GET /api/admin/webhooks/endpoints` and
  `GET /api/admin/webhooks/deliveries?limit=1` unauthenticated → 401
  `{"detail":"Not authenticated"}`.
- **Admin UI deployed**: `GET /admin/webhooks` → 200 SPA HTML; the production
  JS bundle (`assets/index-CSWG-UiK.js`, built by Render — confirming the
  phase-3 finding that Render builds the UI itself) contains the
  `/admin/webhooks` route and the new page's UI strings ("Registered hooks",
  "Queued deliveries", "Minted hooks"), so the Webhooks nav item, page, and
  MachinesPage minted-hooks section all shipped.

## Deferred to the plugin-webhooks plan

Full mint → fire → wake → deliver verification needs a device token, which only
tenant machines hold: the admin machine-env API masks secret values, the local
`fly` CLI has no access token, and issuing a fresh token for a live agent would
revoke that machine's working token (issue_token revokes existing tokens).
The plugin-webhooks deployment runs on the machine and mints with its own token,
so the end-to-end path (sync fire + wake, queue fire + forwarder) is verified
there instead. This was anticipated in PHASE.md and is a sequencing change, not
a coverage loss.

## Surprises / learnings

- **Chrome 151 CDP page-domain wedge**: the long-running :9222 Chrome session
  accepts page-target WebSocket connections but never answers page-session
  commands (browser-level socket works — `Target.getTargets`,
  `Target.createTarget`, `Target.closeTarget` all fine; any command routed to a
  page session times out, on old and freshly created tabs alike). Fire-and-forget
  `Page.navigate` does execute (the tab lands on the URL), but no evaluate/
  screenshot responses ever return. Visual screenshot was therefore skipped;
  bundle-content verification above covers the UI deploy instead. If this
  recurs, restarting the debug Chrome is the fix — deep CDP workarounds are not
  worth it.
- `PUT /json/new?url=` on this Chrome opens the tab but leaves it at
  `about:blank`; target-level `Page.navigate` (even fire-and-forget) is what
  actually navigates.

## Reassessment of remaining phases

- Phase 5 (vanity domain webhooks.luna.com.ai) and phase 6 (Monday migration)
  remain optional/deferred — no changes.
- The gateway is complete and live. Next work item is the plugin-webhooks plan
  (in luna-plugins), which also completes the deferred end-to-end verification.
