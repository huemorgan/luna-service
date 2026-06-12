# 03 — Managed flow: tenant token in, real key out, usage metered

## Preconditions
- Scenarios 01–02 done (`echo-test` service with global keys)
- Stub upstream running on :9009 (echoes received headers as JSON)
- A tenant token for a test agent (issue via the admin keys UI/API or
  provisioning; record the raw `lsv1-...` value)

## Scenario
1. From a terminal:
   `curl -s http://localhost:8100/proxy/echo-test/anything -H "x-api-key: lsv1-<token>"`
2. Read the JSON the stub echoed back
3. Open the admin usage view (or query `usage_events`) for the test agent

## Expected behavior
- The stub reports it received `x-api-key: real-key-AAA` — the priority-1
  global key was injected; the `lsv1-` token did NOT reach the upstream
- The response body comes back to the caller intact (proxy is transparent)
- A `usage_events` row exists: correct agent, service `echo-test`,
  `billable = true`, key = echo-main
- Calling with an invalid token (`lsv1-garbage`) returns 401 and nothing
  hits the stub

## Fail conditions
- Tenant token forwarded upstream
- No usage event, or billable wrong
- Invalid token reaches the upstream
