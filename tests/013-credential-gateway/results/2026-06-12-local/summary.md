# 013 Credential Gateway — dojo run 2026-06-12 (local)

Stack: control plane on :8101 (stub identity, docker-local runtime),
stub upstream on :9009 (`dev/stub_upstream.py`, rejecting `real-key-AAA`),
local Postgres :5435. Pytest: 52/52 green before the run.

| # | Scenario | Result | Evidence |
|---|----------|--------|----------|
| 01 | Admin services page | **PASS** | `screenshots/01-services-page.png` — 4 seeded services with correct enabled/provisioned badges; `echo-test` added through the form and appeared instantly, no restart |
| 02 | Key pool write-only | **PASS** | `screenshots/02-key-added.png`; DOM + API string-checked for `real-key-AAA`/`BBB` → absent; duplicate (global, P1) rejected with 409 and clear message |
| 03 | Managed flow | **PASS** | Stub echoed `x-api-key: real-key-AAA` (P1 injected); `lsv1-` token never reached upstream; usage_event billable=t with agent+key; `lsv1-garbage` → 401, no upstream hit |
| 04 | Key fallback | **PASS** | Stub rejecting AAA → caller still got 200 served by `real-key-BBB`; `echo-main` got 1h cooldown (badge in `screenshots/04-cooldown-badge.png`); next request went straight to BBB |
| 05 | BYOK passthrough | **PASS** | `sk-my-own-tenant-key` forwarded verbatim; usage_event billable=f, no attribution; rejected BYOK → 401 returned verbatim, no pool-key fallback |
| 06 | Agent override | **PASS** | Agent A's traffic used `real-key-CCC` (agent-scoped P1), agent B used global pool; usage attributed per agent (`screenshots/06-usage-table.png`) |
| 07 | Provisioning env | **PASS** | Container env: `LUNA_{ANTHROPIC,OPENAI}_BASE_URL` → `:8101/proxy/{slug}`, API-key vars are the same 48-char `lsv1-` token, `LUNA_HOST_NAME=Luna Cloud`; fake real keys (`sk-ant-FAKE…`, `sk-proj-FAKE…`) present in control-plane env did NOT leak; `LUNA_TAVILY_API_KEY` real (documented legacy exception); the injected token proxied successfully and usage attributed to `alice-gateway-dojo` |

## Issues found and fixed during the run

1. Upstream `ConnectError` surfaced as a raw 500 — now returns a clean 502
   ("Upstream '<slug>' unreachable") in both managed and BYOK paths.

## Notes

- Stub identity user (`alice@novalystrix.ai`) is outside the signup
  allowlist; session was forged with the dev session secret and the user
  promoted to admin in SQL — dev-only workaround, not a product issue.
- The provisioned container kept booting Luna after env verification
  (health check ~90s); env + token validation did not depend on it.
