# Scenario 07 — Conversation persists across container restart

## Preconditions

- Scenario 06 just completed (conversation exists with 5 turns for `alice@example.com`)

## Scenario

1. Stop the Luna container: `docker stop local-luna-app`
2. Wait 5 seconds
3. Start it again: `docker start local-luna-app`
4. Wait for healthcheck to pass: `until curl -fs http://localhost:8080/healthz; do sleep 1; done`
5. Open `http://localhost:8080/` in a fresh browser tab
6. Verify the previous conversation is visible in the sidebar / history
7. Open that conversation
8. Send a new turn: "What was the favorite color I told you earlier?"
9. Wait for response

## Expected Behavior

- The previous conversation appears in the history list (timestamp, title, snippet)
- Opening it shows all 10 prior messages
- New turn 11 is appended correctly
- Luna's reply to turn 11 correctly says "purple" (data restored from DB)

## Fail Conditions

- ❌ Conversation history is empty after restart
- ❌ Conversation is there but messages are missing
- ❌ Luna can't recall purple (memory wasn't actually persisted)
- ❌ Container fails to restart cleanly
- ❌ Migration runs again and breaks data

## Verify

- Sidebar shows the existing conversation
- DOM after opening it shows all 10 prior messages plus the new exchange
- Postgres before AND after restart shows the same `messages` count

## Notes

The most boring possible test — but durability is the foundation. If this fails, the whole platform fails.
