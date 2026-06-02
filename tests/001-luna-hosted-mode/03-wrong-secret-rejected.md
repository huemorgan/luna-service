# Scenario 03 — Wrong proxy secret → 401

## Preconditions

- Local stack up
- Luna's `LUNA_TRUSTED_PROXY_SECRET` is `dev-secret-12345`

## Scenario

Send a request with the user header set but a wrong secret:

```bash
curl -i http://localhost:8000/api/conversations \
  -H "X-Luna-User: alice@example.com" \
  -H "X-Luna-Proxy-Secret: WRONG-SECRET"
```

## Expected Behavior

- HTTP status: **401 Unauthorized**
- Error indicates auth failure (not server error)
- The wrong secret is **not echoed** in the response body or logged unredacted

## Fail Conditions

- ❌ Returns 200 — would mean Luna trusts any request with a user header (catastrophic)
- ❌ Returns the wrong-secret value in the response or logs (info leak)
- ❌ Same response as scenario 02 with no distinction (we should be able to tell from logs/metrics that it was an attempted breach, not a missing header)

## Verify

- HTTP status from `curl -i`
- Container logs: should show a "trusted proxy secret mismatch" warning (with secret REDACTED, not printed)
- Optional: check that repeated wrong-secret attempts don't crash anything (rate limiting is post-MVP, but it shouldn't blow up)

## Notes

This is the most likely real-world attack: someone gets the user header right but doesn't have the secret. The defense holds.
