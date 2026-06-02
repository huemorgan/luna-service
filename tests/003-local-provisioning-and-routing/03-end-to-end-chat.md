# Scenario 03 — Land in chat, full conversation works

## Preconditions

- Scenarios 01-02 just completed (Alice has a running Luna)

## Scenario

A real conversation, end to end, through the control-plane proxy.

1. On `/alice`, send: "Hi Luna, I'm Alice. What's your name?"
2. Wait for streaming reply (should appear character-by-character)
3. Send: "I'm building a multi-tenant version of you. Are you OK with that?"
4. Wait
5. Send: "Please remember that I'm working on luna-service, and my goal is to ship MVP this month."
6. (If approval card appears for memory write: approve it)
7. Send: "Just to test, what am I working on and when do I want to ship?"
8. Wait for response

## Expected Behavior

- Each turn streams smoothly through the proxy (SSE works)
- Turn 7: Luna correctly says "luna-service" and "this month" — proves memory write/read works end-to-end
- No errors, no broken streams
- Network tab: SSE request to `/alice/api/conversations/.../stream` (or similar) — streaming chunks visible

## Fail Conditions

- ❌ Streaming doesn't work (full response only after long pause)
- ❌ Stream cuts off mid-response
- ❌ Luna can't recall what was said earlier in the conversation
- ❌ Memory plugin's approval card doesn't appear (approval engine broken via proxy)
- ❌ After approval, memory write fails silently
- ❌ Turn 7 fails to recall the saved memory

## Verify

- Screenshots after each odd turn
- Network tab showing SSE chunks streaming in real-time
- DB: Alice's `messages` table has correct rows; `memories` table has the new memory

## Notes

This is the actual product test. Forget the infra — does it feel like talking to your own Luna? If yes, MVP is real.
