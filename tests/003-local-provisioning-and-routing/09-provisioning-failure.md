# Scenario 09 — Provisioning failure shows friendly error

## Preconditions

- Fresh DB
- Force a provisioning failure. Easiest ways:
  - Set `LUNA_HOSTED_IMAGE_TAG=does-not-exist:99.99.99` in control plane env (Docker pull fails)
  - OR temporarily stop the tenant Postgres so schema creation fails
  - OR temporarily set an invalid `LUNA_ANTHROPIC_API_KEY` so Luna's health check fails

Pick one for the test (preferably image tag — easiest to undo).

## Scenario

1. Sign in as Alice (new user)
2. Wait through the provisioning screen
3. Observe what happens when provisioning fails

## Expected Behavior

- Provisioning screen detects failure within a reasonable timeout (e.g., 90s max)
- UI shows a clear error: "We couldn't set up your Luna. Please try again." with a "Try again" button
- DB: `agents.status` = `error`, `agents.metadata` has diagnostic info (which step failed)
- Audit log entry exists
- No partial state: if schema was created but container failed, status should still be `error` (operator can clean up)

## Fail Conditions

- ❌ UI spins forever with no timeout
- ❌ Error message is "Internal Server Error" / 500 page
- ❌ Error message exposes internal details (image name, container IDs, stack trace) to the user
- ❌ User is stuck — no way to retry
- ❌ DB is in inconsistent state (e.g., agent row says "running" but no container exists)

## Verify

- Screenshot of error screen
- DB state
- Control plane logs contain a full diagnostic trace
- User-facing message is friendly, not technical

## Notes

Things will fail in production — Fly will be down, the tenant Postgres will hiccup, your image will have a bug. The MVP doesn't need perfect resilience but it needs to fail clearly, not silently.
