# Scenario 04 — Render → Fly internal connectivity

## Preconditions

- Production deployed

## Scenario

From the Render control plane shell (Render dashboard → "Shell" tab on the service):

```bash
# Resolve a Fly Machine URL
curl -v https://<some-known-machine-id>.vm.luna-tenants-prod.fly.dev/healthz

# Verify connection time
time curl -s https://<machine-id>.vm.luna-tenants-prod.fly.dev/healthz

# Test the trusted-proxy header round-trip
curl -v https://<machine-id>.vm.luna-tenants-prod.fly.dev/api/auth/me \
  -H "X-Luna-User: test@example.com" \
  -H "X-Luna-Proxy-Secret: $CLOUD_TRUSTED_PROXY_SECRET"
```

## Expected Behavior

- Healthcheck: 200, response time < 100ms (Render Oregon → Fly SJC over public internet — ~20-30ms RTT + processing)
- Authed call: 200 with user info
- Connection establishes cleanly (no TLS errors)

## Fail Conditions

- ❌ Connection refused / timeout
- ❌ Response time > 1s (something wrong with routing)
- ❌ TLS errors
- ❌ Trusted-proxy auth fails (env var not set on either side, or value differs)

## Verify

- Curl output saved to log
- Time measurements

## Notes

This is "do the cloud regions actually talk to each other reliably?" If not, no user request works. Test BEFORE pointing users at production.
