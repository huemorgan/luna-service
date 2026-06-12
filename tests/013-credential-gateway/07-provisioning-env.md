# 07 — Provisioned machine gets proxy URLs + token, zero real keys

## Preconditions
- Local control plane with `CLOUD_RUNTIME=docker-local`
- Real LLM keys present in the control plane's own env (so the old code
  path WOULD have leaked them — that's the point)

## Scenario
1. Provision a fresh agent (dashboard → New Agent, or the API)
2. When the container is up: `docker inspect luna-<account-slug>` and read
   the `Env` array

## Expected behavior
- `LUNA_ANTHROPIC_BASE_URL` = `<control-plane>/proxy/anthropic`,
  `LUNA_OPENAI_BASE_URL` = `<control-plane>/proxy/openai`
- `LUNA_ANTHROPIC_API_KEY` and `LUNA_OPENAI_API_KEY` are `lsv1-` tenant
  tokens — **NOT** `sk-ant-...` / `sk-proj-...` values
- `LUNA_HOST_NAME` is set (e.g. "Luna Cloud")
- No real Anthropic/OpenAI key appears anywhere in the env array
- Exception (documented): `LUNA_TAVILY_API_KEY` may still be the real key
  until Luna ships 007.001 base-url support for Tavily
- The token in the env verifies against `gateway_tenant_tokens` (hash
  match for this agent)

## Fail conditions
- Any real LLM provider key in the machine env
- Missing base-url vars or host name
- Token not valid for the proxy
