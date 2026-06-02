# Scenario 02 — Phase 003 scenarios re-run on production

## Preconditions

- Production deployed

## Scenario

Run scenarios 01, 03, 05, 06, 07, 08, 11, 12 from phase 003 against `https://luna.com.ai` instead of `localhost:8000`.

(Skip scenarios that require local Docker access; skip stub-identity scenarios.)

## Expected Behavior

- All selected scenarios pass identically against production
- Performance is comparable (provisioning < 30s as in 003)
- No behaviors that worked locally but fail in production

## Fail Conditions

- Any scenario that passed locally but fails in production → file as critical

## Verify

- Cross-reference each scenario's "Verify" section
- Note any platform-specific differences (Fly Machine IDs vs Docker container names, etc.)

## Notes

This catches "works on my machine" syndrome. The most common production-only failures:
- Env vars missing or different
- Internal networking (Render control plane ↔ Fly Machines ↔ Render tenant DB) misconfigured
- HTTPS-only cookies (Secure flag) not propagating
- SSE buffering by Cloudflare or Render
