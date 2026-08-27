# Phase 2 — mint API + public ingress

## Scope
- `cloud/api/webhook_agent_routes.py` — `/api/agent/webhooks/hooks` CRUD, device-token
  auth (035 helper pattern), idempotent upsert on (plugin, name), secret returned only
  on create/rotate, target_path validated to `/api/p/…`, installed_plugins bookkeeping.
  `public_hook_url()` helper (uses new `webhooks_base_url` setting, falls back to base_url).
- `cloud/api/webhook_routes.py` — `GET|POST /api/webhooks/hooks/{agent_slug}/{hook_slug}`:
  - sync: forward raw body + query with passthrough headers (denylist: auth/cookies/
    hop-by-hop/x-luna-*/fly-*/webhook-*) plus standard-webhooks HMAC signed with the
    per-hook secret, `x-luna-hook-name`/`x-luna-hook-plugin`, `x-luna-proxy-secret`,
    `fly-force-instance-id`. ReadTimeout → 504 no retry (double-run risk, 035
    precedent). Other transport error → `_try_wake_agent` → `_wait_machine_ready`
    (poll `/api/health` ≤45 s — the new readiness wait) → retry once. Response
    returned verbatim (challenge handshakes work).
  - queue: JSON envelope (method/query/headers/body + HMAC-of-body with hook secret
    inside the envelope) → relay_deliveries row with target_path → 202.
  - Per-hook delivery stats (best-effort).
- `cloud/main.py`: webhook_agent_router (bare + /proxy) + webhook_relay_router.
- `cloud/config.py`: `webhooks_base_url` (CLOUD_WEBHOOKS_BASE_URL), empty = base_url.

## Design note (deviation from PLAN.md)
Queue-mode deliveries are re-signed by the forwarder with the *relay* secret the
plugin can't derive; the per-hook HMAC therefore rides inside the envelope body
instead of headers. Hosted machines also gate all routes behind x-luna-proxy-secret,
which both paths include.

## Verification
- New `cloud/tests/test_webhooks.py`: mint CRUD + auth, ingress 404/410/413,
  sync forwarding with verifiable signature + header hygiene, queue envelope +
  row, wake-retry and wake-fail paths.
- Full suite back to baseline.
