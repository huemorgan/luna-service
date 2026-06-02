# Scenario 04 — Returning user lands on existing Luna

## Preconditions

- Scenarios 01-03 done (Alice has a Luna with conversation history)

## Scenario

1. Sign Alice out
2. Close all browser tabs
3. Reopen browser, sign back in as Alice
4. Observe what happens

## Expected Behavior

- Lands directly on `/alice` (NOT through provisioning screen again)
- Chat UI loads immediately
- Previous conversation visible in sidebar
- Opening it shows all prior messages intact
- No new Luna container provisioned (still `luna-alice`, still same container ID)
- No new schema created

## Fail Conditions

- ❌ Provisioning screen appears again (means we provision on every login)
- ❌ Second Luna container spawned
- ❌ Conversation history empty (data lost between sessions)
- ❌ Container ID changed (means container was destroyed and recreated)

## Verify

- `docker ps -f name=luna-alice` shows same container ID as before
- DB: still 1 row in `agents`, status=`running` (or `sleeping` if scale-to-zero implemented — but MVP keeps everyone running)
- Conversation list in UI matches previous state

## Notes

The "comes back tomorrow" test — but in seconds. If returning users get re-provisioned, billing breaks and UX is terrible.
