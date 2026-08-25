# 075 — Browser Use gateway routes: fix provisioned-but-blocked (402 sku_unpriced)

## Incident (2026-08-25)

New Luna `vaselin-scanny-2` calls `https://luna.com.ai/proxy/browser-use/browsers`
and gets `402 Payment Required`. The agent surfaces it as "billing issue"; the
Browser Use vendor account has ~$117, which is irrelevant — the request never
leaves the gateway.

## Root cause

`cloud/gateway/route_catalog.py` is deny-by-default: every managed request is
classified by `(service_slug, method, path)`; unknown routes are
`sku_unpriced` — blocked before upstream in enforce mode
(`CLOUD_BILLING_MODE=enforce`, global since Jul 16).

`browser-use` was added to the service registry (`enabled: true`,
`provision_by_default: true`) but the route catalog was never given a single
`browser-use` row. Every request on the service 402s.

**Recurring class**: same thing happened with Tavily (the comment on its row
documents it). The registry and the catalog are two hand-maintained tables
with an invariant between them that nothing checked.

## Fix (this plan)

1. **`_SERVICE_DEFAULTS` in route_catalog** — explicit per-service fallback
   classification, consulted only when no catalog row matches. Deny-by-default
   is untouched for services not listed. `browser-use` → free for its whole v3
   surface (`/browsers`, `/tasks`, `/sessions`, `/files`, …) — same interim
   posture as Composio/Tavily (vendor cost absorbed until a SKU is priced).
   Avoids the second failure mode: enumerating vendor paths row-by-row and
   missing one the plugin uses.
2. **CI guard** — `test_every_enabled_seed_service_has_billing_coverage`:
   every `SEED_SERVICES` entry with `enabled: true` must have ≥1 catalog row
   or a `_SERVICE_DEFAULTS` entry, via new `route_catalog.covered_services()`.
   A service can no longer ship provisioned-but-blocked.
3. **Ops visibility** — `enforcement.prepare` now logs a warning with the
   unpriced reason + route whenever it blocks (or would-block) a route as
   `sku_unpriced`. Previously enforce mode 402'd silently.

## Follow-up (separate plan)

Price a `browser_task` SKU (per-task or per-step metering needs a usage
adapter for model-less per-request SKUs — same deferral as Composio
per-execute) and move `browser-use` from `_FREE` to billed. Provider-add
checklist applies: pricing rollout after publish is mandatory.

## Verification

- `cloud/tests/test_gateway_billing.py` (56) + gateway/discovery/stripe-gateway
  suites (69) green.
- Prod after deploy: `/proxy/browser-use/browsers` no longer 402s;
  vaselin-scanny-2 browser flow works. SSL handshake failure against the
  Merkava gov.il site is unrelated (target-site TLS posture — the reason the
  browser service is used at all).

## Deploy

Control plane on Render `srv-d8g5pd42m8qs73ekk2b0`, autoDeploy off — trigger
deploy via Render API after push.
