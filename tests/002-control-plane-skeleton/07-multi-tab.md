# Scenario 07 — Multi-tab consistency

## Preconditions

- Two browser windows open (same browser profile)
- Logged in as Alice in window A

## Scenario

1. In window B, navigate to `http://localhost:8000/dashboard` → should be logged in already (shared cookies)
2. In window B, click "Sign out"
3. Switch to window A
4. Hit refresh

## Expected Behavior

- After step 1: window B shows dashboard as Alice
- After step 2: window B redirects to landing
- After step 4: window A also logged out (cookie cleared shared across tabs)
- If window A had stale state cached, refresh should now show landing

## Fail Conditions

- ❌ Window A still shows dashboard after window B signed out and refresh (would only be a problem if cookie wasn't cleared)
- ❌ Window A shows authenticated UI but `/api/auth/me` returns 401 (split-brain)

## Verify

- Both windows in same state after each step
- Inspect cookies — single shared session

## Notes

Most users have multiple tabs open. Signing out in one tab should sign out everywhere.
