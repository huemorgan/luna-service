# Scenario 11 — Container restart preserves user data

## Preconditions

- Alice has a Luna with conversation history (scenario 03 done)

## Scenario

1. Kill Alice's Luna container abruptly: `docker kill luna-alice`
2. Watch the control plane detect the failure (via health checks)
3. Observe what happens in Alice's browser if she sends a message during the outage
4. Wait for the container to be restarted (control plane should auto-restart, or operator does manually)
5. Once back, Alice sends a message
6. Verify history is intact

## Expected Behavior

- During outage: Alice's chat shows a friendly "Reconnecting..." state (or 502 → retried automatically)
- Control plane (or Docker's restart policy) brings the container back within ~10s
- Alice's next message succeeds (after retry)
- Conversation history intact (was in Postgres, not container)
- Vault state preserved (key is regenerated deterministically OR persisted somewhere durable)

## Fail Conditions

- ❌ Alice's chat shows a permanent "broken" state requiring page reload
- ❌ History lost after restart (means we stored conversations in container ephemeral state — design bug)
- ❌ Vault key different after restart → can't decrypt prior memories
- ❌ Container never restarts (no restart policy / no orchestration)

## Verify

- Container restart visible in `docker events`
- DB conversation rows unchanged
- Vault key (env var) matches before/after

## Notes

The whole reason we use Postgres + per-tenant schemas instead of SQLite-in-container is that containers die. Make sure data lives outside them.
