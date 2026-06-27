# 026.1 — Virtual keys (control-plane half): E2E scenarios

Backend covered by pytest (`cloud/tests/test_gateway_discovery.py`). These
scenarios verify the device-token discovery contract + provisioning pair end to
end. The luna-side vault UI + `vault.connect()` + agent tools are a separate Luna
proposal (`plans/luna-proposals/026.1-vault-virtual-keys.md`) — NOT in scope here.

## S1 — Discovery endpoint authed by device token
1. Issue an agent a device token (admin → gateway → agents/{id}/token).
2. `GET /api/agent/gateway/services` with `Authorization: Bearer <lsv1 token>`.
3. Response lists services with: slug, display_name, purpose, proxy_url,
   auth_header, auth_scheme, provisioned, has_key, status. NO key values anywhere.
PASS: 200 + correct shape; secrets-free.

## S2 — provisioned vs available
1. Bind plugin-browser → browser-use (has key); agent's plugin_set includes
   plugin-browser. Bind plugin-monday → monday (has key) but agent does NOT have
   plugin-monday installed.
2. Call discovery for the agent.
PASS: browser-use `provisioned:true, has_key:true`; monday
   `provisioned:false, has_key:true, status:"available"`.

## S3 — bad / missing token
1. Call discovery with no token, a garbage token, and a revoked token.
PASS: 401 in every case.

## S4 — single-pair provisioning (additive)
1. Provision an agent.
PASS: env has `LUNA_GATEWAY_URL` (= {base}/proxy) + `LUNA_GATEWAY_TOKEN` (lsv1),
   AND keeps the SDK LLM vars (ANTHROPIC_BASE_URL, OPENAI_API_KEY, …) and the
   per-service vars current plugins still read (back-compat until luna ships
   `vault.connect()`).

## S5 — proxy guardrails (allow/deny + budget)
1. Set an agent gateway policy denying service `browser-use`.
2. The agent calls `/proxy/browser-use/...` with its token.
PASS: 403 (denied); usage event still attributed. Other services unaffected.
3. Non-LLM proxy call (e.g. monday) records a usage_event with request_count≥1
   even when no tokens are reported.
