# Plan 029.1 — Wire credential-gateway provisioning for base-url-capable plugins

> Source: suggestion from the **plugin project** (Luna OSS side). Copied verbatim
> below. This plan lives in luna-service because every change it asks for is on
> the control-plane side (`cloud/gateway/*`, `cloud/api/gateway_*`,
> `cloud/provisioning/*`). The plugin side is already done and live.
>
> Context: follow-on to plan 029 (env visibility + gateway-env backfill). The
> backfill fixed machines missing `LUNA_GATEWAY_URL/TOKEN`, but keyed plugins
> like `plugin-image-gen` (Gemini) still loop on a vault key form because their
> per-service env (`LUNA_GEMINI_BASE_URL` / `LUNA_GEMINI_API_KEY`) is never
> injected — no `GatewayService` row exists for those providers.

---

## Task: wire credential-gateway provisioning for the newly base-url-capable plugins

## Goal
Make keyed plugins auto-resolve their key through the gateway proxy with zero user
prompts. Priority #1: `plugin-image-gen` Gemini (it currently loops on a vault
"gemini_api_key" form because no key reaches it). Then the rest.

## Root cause (today)
`build_gateway_env` (cloud/gateway/provision_env.py) only injects
`LUNA_<SLUG>_BASE_URL` + `LUNA_<SLUG>_API_KEY` for `GatewayService` rows that are
`enabled=True AND provision_by_default=True`. Seeded set is only `anthropic` +
`openai`. None of the image providers / connectors are registered, so nothing is
injected, so the plugins fall back to "ask for a vault key". Plugin install/upgrade
never triggers provisioning, and env is only applied to a machine at *create* time.

The plugin side is already done and live (each declares `credential_slots()` with
`env_base_url_var` and routes through `LUNA_<SLUG>_BASE_URL` when set). Env var names
follow `default_names(slug)` exactly: `LUNA_<UPPER(slug, - → _)>_API_KEY` /
`_BASE_URL`.

## 1. Register the GatewayServices
Add these to `SEED_SERVICES` in cloud/gateway/registry.py (or create via the admin
Key Registry UI). `upstream_url` = the real API root the plugin appends paths to;
the proxy maps `{gateway}/proxy/<slug>/...` → `<upstream_url>/...`.

| slug            | upstream_url                                          | auth_style (how gateway must attach the REAL key) | provision_by_default |
|-----------------|------------------------------------------------------|---------------------------------------------------|----------------------|
| gemini          | https://generativelanguage.googleapis.com/v1beta     | query param `key=` (plugin sends `?key=<token>`)  | true                 |
| openai          | https://api.openai.com/v1                             | header `Authorization: Bearer <key>`              | true                 |
| bfl             | https://api.bfl.ai                                    | header `x-key: <key>`                             | true (see caveat)    |
| giphy           | https://api.giphy.com/v1/gifs                         | query param `api_key=` (plugin sends NO key)      | false → membership   |
| render          | https://api.render.com/v1                             | header `Authorization: Bearer <key>`              | false → membership   |
| cloudflare      | https://api.cloudflare.com/client/v4                  | header `Authorization: Bearer <key>`              | false → membership   |
| monday          | https://api.monday.com/v2                             | header `Authorization: <key>` (raw, no "Bearer")  | false → membership   |
| browser-use     | https://api.browser-use.com/api/v2                    | header `X-Browser-Use-API-Key: <key>`             | false → membership   |
| funnelfighters  | https://funnelfighters.io                             | header `Authorization: Bearer <key>` (+ org id)   | false (see caveat)   |

Notes:
- `gemini` and `giphy` are **query-param auth** — the proxy must inject the real key
  as a query param, not a header. Confirm cloud/api/gateway_proxy.py supports
  query-param injection (composio/tavily are header-based; this may be new code).
- Set `provision_by_default=true` only for what every machine should always get
  (the image providers). Connectors should be membership-driven (only inject when
  the plugin is installed) — that path (`PLUGIN_KEY_SERVICES` / catalog binding)
  is described in plans/change-all-to-key-provisioning/luna-service-suggestion.md
  and is NOT built yet. If you want them working before that lands, temporarily set
  `provision_by_default=true`.

## 2. Add a pool key per service
Admin Key Registry (cloud/api/gateway_admin_routes.py). Without an active pool key
the proxy returns 502 at request time (key_pool.resolve_keys in gateway_proxy.py).
Env vars are still injected regardless, so add the keys.

## 3. Re-provision EXISTING running tenants (the part that actually unblocks the screenshot)
`build_gateway_env` only runs inside `_provision_core` (cloud/provisioning/workflow.py:131),
and the runtime (fly_machines.py / docker_local.py) only applies env at machine
**create**. A user who already has a running machine will NOT get the new
`LUNA_GEMINI_*` env from a plugin upgrade or a registry edit.

So after steps 1–2, for each affected tenant either:
- call `update_machine_env` with the freshly built gateway env, or
- destroy/recreate the machine.

CAVEAT — token rotation: `issue_token` (cloud/gateway/tokens.py) revokes prior
tokens every time `build_gateway_env` runs. If you rebuild env but don't push the
new token to the machine, the machine keeps a revoked token → 401 at the proxy.
So the env push and the token issue must go together.

## 4. Verify (acceptance)
- Provision/refresh a tenant, exec into it, confirm `LUNA_GEMINI_BASE_URL` and
  `LUNA_GEMINI_API_KEY` are set in the process env.
- In chat: "generate an image of a red bicycle" → image-gen calls Gemini through
  `{gateway}/proxy/gemini` with the token, gateway swaps in the real key, image
  renders inline. No vault prompt.

## Caveats to resolve (don't skip)
1. **FLUX (bfl) async polling** — `_flux_generate` submits to
   `{base}/v1/<model>`, then polls the **absolute `polling_url`** returned by BFL
   (providers.py:305-311), which points at the real `api.bfl.ai`, not the proxy.
   In proxy mode that poll hits the real API with the gateway token → fails. Either
   the gateway must rewrite `polling_url` in the submit response to point back
   through `{gateway}/proxy/bfl`, or hold off on proxying bfl. Gemini/OpenAI are
   synchronous and fine.
2. **giphy token-less requests** — in proxy mode the plugin sends NO credential
   at all (query-param auth, gateway appends `api_key`). Decide how the proxy
   authenticates the tenant for giphy (network/machine identity, or require the
   plugin to send the token in a header). Flag back if the plugin needs to change.
3. **monday** — only the GraphQL data endpoint is proxied; the OAuth token
   exchange stays on `auth.monday.com`. Don't route OAuth through the proxy.
4. **funnelfighters** — needs both an API key (proxiable) AND an `x-organization-id`
   (not a pool secret). The plugin still resolves org id from vault/env, so gateway
   only swaps the key; make sure org id is still provided some other way.

## Cleanup
Once `plugin-web-access` (tavily) is confirmed proxying, remove `LUNA_TAVILY_API_KEY`
from `LEGACY_REAL_KEY_VARS` in cloud/gateway/provision_env.py (the seed comment is
already stale — the plugin has base-url support).
