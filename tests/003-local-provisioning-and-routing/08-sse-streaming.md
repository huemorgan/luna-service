# Scenario 08 — SSE streaming through proxy works

## Preconditions

- Logged in as Alice with running Luna

## Scenario

1. Open browser dev tools → Network → filter "EventStream"
2. Send a long-ish message: "Write me a 200-word essay about why moons are mysterious."
3. Observe the EventStream tab during response generation
4. Verify text appears in the UI character-by-character (not all at once)
5. Open a second tab / window and run an unrelated request mid-stream — does the streaming continue uninterrupted?

## Expected Behavior

- EventStream shows SSE messages arriving in real-time (timestamps spread over the response duration, not all bunched at the end)
- UI updates progressively
- Other concurrent requests don't disrupt the stream
- Stream completes cleanly with a final "[DONE]" event or equivalent
- Connection closes after stream ends (no hanging connection)

## Fail Conditions

- ❌ Full response only arrives at the end (proxy is buffering — common nginx misconfig)
- ❌ Stream cuts off before completion
- ❌ UI shows partial then jumps to full (means buffering and replay)
- ❌ Connection stays open after stream completes
- ❌ Stream stalls if user navigates away mid-response (should gracefully close)

## Verify

- Network tab EventStream view showing event-by-event timing
- Screenshot of UI mid-stream (partial response visible)
- Control plane logs: no warnings about buffer issues

## Notes

SSE through reverse proxies is famous for breaking. The proxy MUST disable buffering for these endpoints (`proxy_buffering off` in nginx terms; FastAPI's `StreamingResponse` handles it but needs the right `Content-Type` and no intermediate buffering).
