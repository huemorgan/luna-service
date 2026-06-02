# Scenario 06 — Session persists across browser refresh

## Preconditions

- Logged in as Alice

## Scenario

1. From dashboard, hit browser refresh (F5)
2. Open new tab to `http://localhost:8000/dashboard`
3. Close browser entirely, reopen, hit `http://localhost:8000/dashboard`

## Expected Behavior

- All three actions land on dashboard, still logged in as Alice
- No re-authentication prompt

## Fail Conditions

- ❌ Refresh kicks user back to landing
- ❌ New tab requires re-login
- ❌ Closing/reopening browser loses session (unless we want session-cookie-only behavior, but cookie should be persistent)

## Verify

- Session cookie has reasonable expiry (e.g., 30 days), NOT `Expires: 0` or session-scoped
- After each action, `/api/auth/me` still returns user info

## Notes

Session UX matters. If users have to log in every time they refresh, they leave.
