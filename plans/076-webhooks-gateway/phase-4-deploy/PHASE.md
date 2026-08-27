# Phase 4 — deploy + production verification

## Scope
- Fetch/rebase on origin/main (in case upstream moved), re-run suite if it did.
- Push commits c7a3609 / 44b0725 / 71839a3 to huemorgan/luna-service main
  (`gh auth switch` to huemorgan first). Render autodeploys; migration 0016
  (webhook_endpoints + relay_deliveries.target_path) applies via migrate.py on boot.
- Watch the deploy: poll https://luna.com.ai health / a new route until the new
  code answers (404 vs 405 signatures on /api/webhooks/hooks/...).

## Production verification
1. New ingress route exists: GET /api/webhooks/hooks/x/y → 404 (not the SPA).
2. Mint a hook for the QA tenant using its device token (from the machine env via
   the admin env API or Fly), via POST /api/agent/webhooks/hooks.
3. Fire the sync hook with curl; confirm 200/challenge passthrough and that the
   machine wakes if stopped.
4. Mint a queue hook; fire; confirm 202 and delivery row on
   /api/admin/webhooks/deliveries (or DB) reaches delivered/dead as expected.
5. Admin UI: /admin/webhooks renders in the left pane (verify via CDP browser
   session on :9222 per production-verify memory).
6. Delete QA hooks afterward.

Note: full plugin-side verification (HMAC verify, bus events, triggers) happens in
the plugin-webhooks plan; this phase proves the gateway alone.
