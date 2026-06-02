# Scenario 03 — Sign out clears session

## Preconditions

- Logged in as Alice

## Scenario

1. From dashboard, click "Sign out" button
2. Observe redirect
3. Inspect cookies
4. Attempt to visit `/dashboard` directly
5. Attempt to call `GET /api/auth/me`

## Expected Behavior

- Redirects to landing (`/`)
- Session cookie cleared (or set to expire in the past)
- `/dashboard` redirects to `/` (or shows landing with "Sign in" CTA)
- `/api/auth/me` returns 401

## Fail Conditions

- ❌ Stays on dashboard after click
- ❌ Cookie still has session value
- ❌ Can still access `/dashboard` after sign-out
- ❌ `/api/auth/me` still returns user data

## Verify

- Cookie inspector before and after sign-out
- Direct URL hits show expected behavior
- DB: no row deleted (sign-out just clears session, doesn't delete account)

## Notes

If users can't sign out, they don't trust us with their data.
