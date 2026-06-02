# Scenario 01 — Header-authenticated request succeeds

## Preconditions

- Local stack up (`dev/local-luna/make up`)
- Luna running in trusted-proxy mode
- Nginx (fake control plane) configured to inject:
  - `X-Luna-User: alice@example.com`
  - `X-Luna-Proxy-Secret: dev-secret-12345`

## Scenario

1. Open browser to `http://localhost:8080` (the nginx proxy port)
2. Verify: the page loads directly to Luna's chat UI (no login screen)
3. Type a message: "Hi, who are you?"
4. Wait for Luna's streaming reply
5. Open browser dev tools → Network tab → find the SSE request
6. Verify the request headers include `X-Luna-User: alice@example.com`

## Expected Behavior

- Chat UI loads immediately, NO login or signup screen visible
- Luna's identity panel (top-left or wherever) shows the user is `alice@example.com`
- Streaming reply appears character-by-character
- Reply is a normal Luna intro (mentions being Luna, agent, etc.)
- Request includes the trusted-proxy headers

## Fail Conditions

- ❌ Login or signup screen appears at all
- ❌ "Unauthorized" or 401 error visible
- ❌ Chat fails to send / no streaming response
- ❌ Luna refers to itself as a "guest" or doesn't recognize an owner
- ❌ Network tab shows missing X-Luna-User header

## Verify

- Screenshot: chat page with Luna's first reply visible
- DOM excerpt: top-bar showing user identity
- Terminal: `docker logs local-luna-app | grep "X-Luna-User"` shows the header being received

## Notes

This is the **happiest path** — trust mode is working end-to-end. If this fails, nothing else in Phase 001 will work.
