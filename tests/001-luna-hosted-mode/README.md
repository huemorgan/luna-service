# Phase 001 — Test Scenarios

Dojo-style scenarios for verifying Luna's trusted-proxy auth mode. The LLM runs these in a browser (or via curl for API-level scenarios), screenshots/captures, and judges pass/fail.

## Setup (Once)

Before running any scenario:

```bash
cd dev/local-luna
make up
# Wait for: postgres ready, luna ready, nginx (fake proxy) ready
```

Verify:
- `docker ps` shows `local-luna-postgres`, `local-luna-redis`, `local-luna-app`, `local-luna-proxy`
- `curl -s http://localhost:8080/healthz` (through proxy) returns 200

## Scenarios

| # | Scenario | File |
|---|----------|------|
| 01 | Header-authenticated request succeeds | `01-header-auth-succeeds.md` |
| 02 | Missing user header → 401 | `02-missing-header-rejected.md` |
| 03 | Wrong proxy secret → 401 | `03-wrong-secret-rejected.md` |
| 04 | Direct access to Luna (bypass proxy) → 401 | `04-direct-bypass-rejected.md` |
| 05 | UI hides login screen in trusted mode | `05-ui-skips-login.md` |
| 06 | Full chat conversation through proxy | `06-chat-conversation.md` |
| 07 | Conversation persists across container restart | `07-persistence-across-restart.md` |
| 08 | Schema-scoped DB connection works | `08-schema-scoping.md` |
| 09 | Local auth mode still works (backward compat) | `09-local-mode-still-works.md` |
