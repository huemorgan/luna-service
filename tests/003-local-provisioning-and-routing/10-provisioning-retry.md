# Scenario 10 — Retry after provisioning failure works

## Preconditions

- Scenario 09 completed (Alice has an agent row in `error` state)

## Scenario

1. Fix the underlying failure (e.g., restore correct image tag, restart Postgres, etc.)
2. From Alice's error screen, click "Try again"
3. Observe behavior

## Expected Behavior

- Retry succeeds within normal provisioning time
- Same `agents.id` is reused (don't create a new row)
- If schema was already created in the failed attempt, it's reused (NOT dropped and recreated)
- If vault key was already generated, it's reused (NOT regenerated)
- If container was created but unhealthy, the unhealthy one is destroyed before retry
- End state: agent `status='running'`, identical to a successful first-time provision

## Fail Conditions

- ❌ Retry creates a duplicate agent row
- ❌ Retry creates a duplicate schema (`luna_user_alice_2`)
- ❌ Vault key changes between attempts (data encrypted in old attempt becomes unreadable)
- ❌ Multiple containers created
- ❌ "Already exists" errors crash the retry

## Verify

- DB: 1 row in agents, 1 schema in tenant DB
- Container has the same vault key as initial provisioning attempt
- Logs show "schema exists, skipping creation", "vault key exists, reusing"

## Notes

Idempotency is the only sane error-recovery strategy at scale. Get it right early or pay forever.
