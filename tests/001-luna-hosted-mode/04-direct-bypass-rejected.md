# Scenario 04 — Direct access to Luna (bypass proxy) → 401

## Preconditions

- Local stack up
- Luna's container exposes port 8000 (default in dev) — in production, Luna would be on internal-only network and unreachable

## Scenario

From the host, try to hit Luna directly (NOT through nginx on port 8080):

```bash
curl -i http://localhost:8000/
curl -i http://localhost:8000/api/conversations
curl -i http://localhost:8000/api/conversations \
  -H "X-Luna-User: attacker@evil.com"
```

## Expected Behavior

- All three requests → **401** (or refused connection if Luna is bound only to internal interface)
- Even with a user header, without the proxy secret → 401

## Fail Conditions

- ❌ Any of the requests returns 200
- ❌ Returns data without the proxy secret

## Verify

- Status of each request
- Logs show all three as auth failures

## Notes

In production, Luna's listening port is on Fly's internal network only (not publicly addressable). In local dev, the port is exposed for debugging, so this scenario explicitly tests that the application-layer auth is the security boundary regardless of network exposure.

This is "defense in depth" — the network layer should also restrict access, but if it ever fails (misconfiguration), the application layer catches it.
