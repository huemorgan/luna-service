# Scenario 02 — Provisioning status screen polls and transitions

## Preconditions

- Same as scenario 01

## Scenario

1. Start signup flow
2. Land on the provisioning screen
3. Watch the network tab → identify the polling request to `/api/agents/me/status`
4. Note the polling interval
5. Observe the visual state of the page throughout

## Expected Behavior

- Polling cadence: every 1-3 seconds (reasonable)
- Visual feedback: spinner is animating, status text updates if backend reports phase ("Creating database", "Booting", "Ready")
- When agent flips to `running`: page transitions smoothly to chat (NOT a hard refresh)
- Total time visible to user: 15-40 seconds (image already pulled)

## Fail Conditions

- ❌ Page is static / no spinner animation
- ❌ No polling (status would never update)
- ❌ Polling every 100ms (DDOSes own server)
- ❌ Hard page refresh on transition (jarring UX)
- ❌ Page just says "loading" forever even after agent is ready (frontend doesn't detect transition)

## Verify

- Network tab screenshot showing polling requests
- Screenshots of provisioning screen at start, middle, transition moment
- Page transition feels smooth (qualitative judgment)

## Notes

This is "design while you wait" — even a 30-second wait feels OK if the system communicates clearly what's happening. A 30-second blank screen feels broken.
