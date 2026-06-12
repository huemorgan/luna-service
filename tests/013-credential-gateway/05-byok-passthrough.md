# 05 — BYOK passthrough: non-lsv1 credential forwarded unchanged

## Preconditions
- Scenarios 01–03 done

## Scenario
1. `curl -s http://localhost:8100/proxy/echo-test/anything -H "x-api-key: sk-my-own-tenant-key"`
2. Read the echoed headers
3. Check usage events

## Expected behavior
- The stub reports it received `x-api-key: sk-my-own-tenant-key` — exactly
  the credential the caller sent. The proxy did NOT substitute a pool key
- A usage event exists with `billable = false` and no key/agent attribution
- If the stub is told to reject that key (401), the caller receives the
  401 verbatim — the proxy does NOT fall back to pool keys for BYOK
- The BYOK credential value appears in no control-plane log line and no DB
  column (spot-check the uvicorn output and `usage_events`)

## Fail conditions
- Pool key substituted for a BYOK request
- BYOK metered as billable
- Fallback to our keys on BYOK failure
- BYOK credential persisted or logged
