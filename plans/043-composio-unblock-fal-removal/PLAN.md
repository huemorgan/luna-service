# 043 — Unblock Composio proxy billing + remove fal gateway service

## Context

The Connectors page (plugin-connectors settings UI) fails with
"Service unavailable (HTTP 502)". Live diagnosis (2026-07-16, vaselin canary):

```
GET https://luna.com.ai/proxy/composio/toolkits?limit=1
→ 402 {"error":{"type":"billing","code":"sku_unpriced",
       "message":"This operation is not enabled for platform-managed billing."}}
```

Root cause chain:
1. The route catalog (`cloud/gateway/route_catalog.py`) has **zero composio
   entries** → `classify()` returns None → `unknown_route` → `sku_unpriced`.
2. The vaselin account is billing-**enforced** (canary override) → fail closed
   with 402. Non-enforced accounts pass but log `would_block` noise.
3. plugin-connectors `routes.py` wraps the provider error in
   `HTTPException(502, …)`; the settings UI renders its generic
   "upstream provider may be down" message.

Not the cause: the composio gateway service itself is healthy (enabled,
provisioned by default, 1 key), and the webhook relay
(`POST /api/webhooks/composio`) is separate ingress, unaffected.

The `composio_request` SKU exists in the commercial config but is **disabled**
(fails closed by design). The current enforcement pipeline is model-centric
(extract_model → tier → margin from `llm_constants`); it cannot rate a
model-less per-request SKU without new machinery. The product UI already says
"Included with Luna Cloud" for Composio, so:

**Decision: classify all composio proxy routes as FREE** (phase 1, this plan).
Metered per-execute pricing (enabling `composio_request` with
`credits_per_request`) is deferred — it needs enforcement support for
model-less SKUs and a pricing decision (phase 2, separate plan when wanted).

## Part A — Composio route catalog entries (code)

`cloud/gateway/route_catalog.py`: add explicit `_FREE` entries for exactly the
paths plugin-connectors calls (deny-by-default stays for everything else).
Wildcard `*` matches exactly one segment.

```python
# Composio (plan 043): connector management + tool execution ride the
# proxy; all free — Composio is flat-rate to Luna ("Included with Luna
# Cloud"). Per-execute metering is deferred until enforcement can rate
# model-less per-request SKUs.
("composio", "GET",    "/toolkits"): _FREE,
("composio", "GET",    "/toolkits/*"): _FREE,
("composio", "GET",    "/tools"): _FREE,
("composio", "POST",   "/tools/execute/*"): _FREE,
("composio", "POST",   "/auth_configs"): _FREE,
("composio", "POST",   "/connected_accounts"): _FREE,
("composio", "POST",   "/connected_accounts/link"): _FREE,
("composio", "GET",    "/connected_accounts/*"): _FREE,
("composio", "DELETE", "/connected_accounts/*"): _FREE,
("composio", "GET",    "/triggers_types"): _FREE,
("composio", "POST",   "/trigger_instances/*/upsert"): _FREE,
("composio", "DELETE", "/trigger_instances/manage/*"): _FREE,
```

Source of truth for the path list: `plugin-connectors/providers/composio.py`
(every `self._request(...)` call site). Note `free` routes short-circuit in
`enforcement.prepare()` before version/tariff resolution — no rates, no holds,
no BillableEvents.

Tests (`cloud/tests/test_gateway_billing.py`):
- each path above classifies as `free`;
- deny-by-default preserved: e.g. `POST /toolkits`, `GET /tools/execute/x`,
  `DELETE /trigger_instances/*` (wrong arity) → None;
- wildcard arity: `/trigger_instances/a/b/upsert` → None.

## Part B — Remove the fal gateway service (prod ops only, no code)

Nothing references fal anywhere (luna-service, luna, luna-plugins — the
image-gen plugin uses gemini/openai/BFL). The `fal` GatewayService row was
created via admin API (it is not in `registry.py` seeds), is enabled +
`provision_by_default: true`, and holds 1 stored key — so every machine gets
dead `LUNA_FAL_API_KEY` / `LUNA_FAL_BASE_URL` env vars.

Steps (admin API, base `https://luna-service.onrender.com`):
1. `PATCH /api/admin/gateway/services/fal`
   `{"enabled": false, "provision_by_default": false}` — proxy rejects the
   slug from then on; new machines stop receiving the env vars.
2. `GET /api/admin/gateway/services/fal/keys` → `DELETE /api/admin/gateway/keys/{id}`
   — remove the stored (encrypted) fal API key.
3. Leave the DB row (disabled) for audit; there is no DELETE /services route.
4. Existing machines keep the now-inert env vars; they disappear naturally on
   machine recycle. No backfill needed (backfill only adds/updates keys).
5. Roy: revoke the key at fal.ai dashboard (Luna cannot do this) — optional,
   the key no longer exists anywhere but fal's own dashboard after step 2.

## Rollout order

1. Land Part A, run `.venv/bin/python -m pytest cloud/tests -q`, push (main
   auto-deploys via deploy_hook).
2. Verify live on canary (enforced account, Rayla machine token read from Fly):
   `GET /proxy/composio/toolkits?limit=1` → 200 JSON; Connectors page loads;
   confirm NO BillableEvent rows appear for the call.
3. Execute Part B; verify `GET /proxy/fal/anything` now fails with a
   service-disabled error and the key list is empty.

## Out of scope

- Phase 2 metering of composio executes (`composio_request` SKU): needs
  model-less per-request rating in `enforcement.prepare()` + a price decision.
- plugin-connectors 502 wrapping (it masks structured billing errors as
  "upstream down") — cosmetic once routes are free; candidate for a plugin fix
  that surfaces `error.type == "billing"` messages verbatim.
- Webhook relay: already works, untouched.
