# Scenario 06 — Full chat conversation through proxy

## Preconditions

- Local stack up
- Anthropic / OpenAI key configured in Luna's env
- Fresh DB (no prior conversations for `alice@example.com`)

## Scenario

1. Open `http://localhost:8080/`
2. Send turn 1: "What's your name?"
3. Wait for full response
4. Send turn 2: "What did I just ask you?"
5. Wait for response
6. Send turn 3: "Remember that my favorite color is purple."
7. Wait for response (might trigger an approval card depending on Luna config — approve if so)
8. Send turn 4: "What's my favorite color?"
9. Wait for response
10. Send turn 5: "Tell me a one-paragraph story about a moon and a rabbit."

## Expected Behavior

- Each turn produces a coherent streaming response
- Turn 2: Luna correctly references what was asked in turn 1
- Turn 4: Luna correctly recalls "purple"
- Turn 5: A coherent short story (judged qualitatively — does it feel like a real story?)
- The conversation timeline in the UI shows all 10 messages (5 user, 5 assistant) in order
- No errors, no broken streams, no truncated responses

## Fail Conditions

- ❌ Any turn errors out
- ❌ Streaming breaks mid-response
- ❌ Luna forgets context within the conversation (turn 4 fails)
- ❌ Story is gibberish / off-topic / clearly broken
- ❌ Message ordering is wrong in UI
- ❌ Approval card never appears for memory-write but turn 4 still works (means memory wrote without approval — separate bug)

## Verify

- Screenshots at end of each odd-numbered turn
- DOM snapshot of message list at end (5 user, 5 assistant, correct order)
- Container logs free of unexpected errors
- Postgres: `SELECT count(*) FROM messages` should equal 10

## Notes

This is more than an isolated tech test — it's a real conversation. The point is to demonstrate Luna feels alive through the proxy, not just that bits flow through. If a real human had this conversation, would they think the system works? That's the bar.
