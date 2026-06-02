# Scenario 02 — Missing user header → 401

## Preconditions

- Local stack up
- A `curl` available

## Scenario

```bash
# Hit the proxy directly with no extra headers, but still going through nginx
# (this requires temporarily reconfiguring nginx OR using a separate test endpoint)

# Easiest: hit Luna directly without the trusted-proxy secret OR user
curl -i http://localhost:8000/api/conversations
# (Luna is on 8000, nginx proxy is on 8080)
```

OR, if Luna is not directly reachable from host:

```bash
docker exec local-luna-app curl -i http://localhost:8000/api/conversations
```

## Expected Behavior

- HTTP status: **401 Unauthorized**
- Response body: JSON error message mentioning auth failure (specific wording doesn't matter, must be clear it's auth-related)
- No data leaked in the response (no actual conversations returned)

## Fail Conditions

- ❌ Returns 200 with any data
- ❌ Returns 500 (server error — should be a clean 401)
- ❌ Response body mentions internals like stack traces or DB queries
- ❌ Status is 403 instead of 401 (could be acceptable but 401 is more correct here — missing credentials, not wrong permissions)

## Verify

- HTTP response headers shown by `curl -i`
- Response body
- Container logs: should show a "missing trusted proxy headers" warning, not a stack trace

## Notes

This proves the security boundary works — Luna does not let unauthenticated requests through just because trusted-proxy mode is configured. The proxy must actually be in the path AND the secret must match.
