# 029 — Machine env-var visibility — scenarios

Dojo-style. LLM is the test runner: drive the admin UI in a browser, verify with your own eyes.

## S1 — Per-machine Env vars tab
1. Admin → Machines. Expand any machine.
2. Click the **Env vars** tab.
3. Expect a table of the machine's actual env vars.
4. Secrets (`LUNA_VAULT_MASTER_KEY`, `LUNA_DATABASE_URL`, `LUNA_TRUSTED_PROXY_SECRET`, `*_API_KEY`, `LUNA_GATEWAY_TOKEN`, `LUNA_COMPOSIO_WEBHOOK_SECRET`) are **masked** (`•••• (N chars)`), never shown in clear.
5. Non-secret vars (`LUNA_ENV`, `LUNA_CORS_ORIGINS`, `*_BASE_URL`, `LUNA_FILES_ROOT`, model vars) show their real value.

## S2 — Missing-key flag
1. On a machine provisioned before the gateway pair shipped, the tab shows a warning strip listing expected-but-missing keys (e.g. `LUNA_GATEWAY_URL`, `LUNA_GATEWAY_TOKEN`).
2. On a freshly (re)provisioned machine, no missing keys.

## S3 — Defaults → Env vars
1. Admin → Defaults → **Env vars** tab.
2. Expect the env template every new machine receives.
3. Dynamic per-agent vars (`LUNA_GATEWAY_TOKEN`, `*_API_KEY`, `LUNA_DATABASE_URL`, `LUNA_VAULT_MASTER_KEY`, `LUNA_TRUSTED_PROXY_SECRET`, `LUNA_COMPOSIO_WEBHOOK_SECRET`, `LUNA_MODEL_CATALOG`) show a **placeholder** value (`{{…}}`) and a `dynamic` badge — not a real value.
4. Static vars (`LUNA_ENV`, `LUNA_GATEWAY_URL` = `<base>/proxy`, `*_BASE_URL`, files vars) show concrete values.

## S4 — No secret leakage
1. In neither view does any real token / key / password / DB URL appear in clear text.
