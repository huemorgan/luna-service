# 080 — TypeSafe gateway service

Source: luna-plugins `plans/018-plugin-typesafe` (Phase 2). Authorized by Roy 2026-09-17.

## Goal

`plugin-typesafe` gets its key from the gateway in proxy mode, and its calls
are not blocked by billing enforce.

## Changes

1. `cloud/gateway/registry.py` `SEED_SERVICES`: add `typesafe`
   (`https://api.typesafe.ai`, `header:Authorization:Bearer`, enabled,
   `provision_by_default=False`). The production row was already created by
   hand through the admin API; the seed is insert-if-missing, so this only
   makes fresh databases match.
2. `registry.py` `KNOWN_SERVICES`: add `typesafe` so the key suggester
   pre-fills it. `PLUGIN_KEY_SERVICES` untouched (`plugin-typesafe` →
   `typesafe` derives).
3. `cloud/gateway/route_catalog.py` `_SERVICE_DEFAULTS["typesafe"] = _FREE`.
   Without it every call 402s `sku_unpriced` under enforce, and
   `test_gateway_billing` fails on the new seed slug. Vendor cost is about
   $0.04 per million input tokens; a priced SKU waits for measured usage.

## Verify

- `cloud/tests/test_gateway_billing.py`, `test_service_keys.py` pass.
- After deploy: a tenant with the proxy binding calls
  `/proxy/typesafe/v1/systemone` and gets 200, not 402.
