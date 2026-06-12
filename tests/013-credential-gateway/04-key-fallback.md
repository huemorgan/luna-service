# 04 — Key fallback: priority-1 fails, priority-2 serves

## Preconditions
- Scenario 03 done
- Stub upstream supports a "reject this key" mode: it returns 401 when the
  injected key equals a value it was told to reject (`real-key-AAA`)

## Scenario
1. Tell the stub to reject `real-key-AAA` (env var or query param, per stub)
2. `curl -s http://localhost:8100/proxy/echo-test/anything -H "x-api-key: lsv1-<token>"`
3. Read the echoed headers
4. Refresh the admin services page; look at the echo-test key pool

## Expected behavior
- The request still succeeds (HTTP 200 to the caller)
- The stub reports it received `real-key-BBB` — the proxy retried with the
  priority-2 key after the 401
- In the admin UI, `echo-main` now shows a cooldown (auth-failure cooldown),
  `echo-backup` shows recent use
- A second request goes straight to `real-key-BBB` (no retry round-trip
  while the cooldown lasts)

## Fail conditions
- Caller gets the 401 instead of a fallback success
- More than one retry per request (stub sees 3+ attempts)
- Cooldown not recorded / not visible
