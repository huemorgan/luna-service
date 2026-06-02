# Scenario 03 — Fly Machine lifecycle

## Preconditions

- Production deployed
- Test account "Alice" has signed up and has a Fly Machine running

## Scenario

Via Fly CLI / API:

1. List Alice's Machine: `fly machines list --app luna-tenants-prod | grep luna-alice`
2. Note its state (should be `started`)
3. Suspend it: `fly machines suspend <machine-id>`
4. From Alice's browser, try to send a message
5. Observe wake-up time
6. Verify message succeeds after wake
7. Inspect machine again — should be back to `started`
8. (Manual operator action) Destroy machine: `fly machines destroy <machine-id> --force`
9. From Alice's browser, try to send a message
10. Observe what happens

## Expected Behavior

- Suspended machine wakes on request (< 1s ideally; up to 3s acceptable for MVP)
- Wake is transparent to user (might see a 1-2s "thinking" pause, no error)
- After destroy: control plane detects missing machine, transitions agent to `error`, friendly UI message
- Agent retry button works (would re-provision)

## Fail Conditions

- ❌ Wake takes > 5s consistently
- ❌ First request after wake fails (race condition with health check)
- ❌ After destroy, UI shows confusing error / 502 / blank screen
- ❌ Destroy not detected by control plane

## Verify

- Fly CLI output before/after each operation
- Browser screenshots during wake and after destroy
- Control plane logs showing detection events

## Notes

For MVP, all Lunas are always-on (no scheduled suspension). But manual suspension MUST work because we use it to:
- Cost control (suspend an abusing user's machine)
- Maintenance (suspend before destructive ops)
- Future: scheduled scale-to-zero

If wake doesn't work, the future scale-to-zero strategy is dead before it starts.
