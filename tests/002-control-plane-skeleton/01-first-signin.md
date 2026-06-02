# Scenario 01 — First-time user sign in

## Preconditions

- Control plane up
- Fresh DB (`DELETE FROM users; DELETE FROM accounts; DELETE FROM memberships;` or run `make cloud-reset`)
- Identity provider configured (stub or google)

## Scenario

1. Open `http://localhost:8000/` in incognito
2. Verify landing page shows: Luna branding, "Sign in with Google" button
3. Click "Sign in with Google"
4. Complete the OAuth flow:
   - **Stub mode:** click the test user picker → select "Alice (alice@example.com)"
   - **Google mode:** complete real Google consent screen with a test account
5. Observe the redirect
6. Land on `/dashboard`
7. Inspect the dashboard

## Expected Behavior

- Step 6: URL is `/dashboard` (or `/{account_slug}` if we route there directly — TBD per implementation)
- Dashboard shows:
  - User's avatar + name (top-right)
  - Account name (defaults to user's display name, e.g., "Alice's Workspace")
  - Account slug visible (e.g., `alice`)
  - "Your Luna" card with status "Not provisioned yet — coming in phase 003"
  - Sign out button
- DB state:
  - 1 row in `users` (with `google_sub` matching the test account)
  - 1 row in `accounts` (created_by = users.id, slug auto-generated from email)
  - 1 row in `memberships` (role=owner, status=active)
  - 0 rows in `agents` (correct for this phase)
- Session cookie set: `cloud_session` (HttpOnly, SameSite=Lax)

## Fail Conditions

- ❌ OAuth flow errors out
- ❌ Lands somewhere other than the dashboard
- ❌ Dashboard renders before user info loads (flash of empty state)
- ❌ User row created but no account / no membership (atomicity broken)
- ❌ Account slug has special characters or is empty
- ❌ Session cookie missing HttpOnly flag (security regression)

## Verify

- Screenshot of landing page before click
- Screenshot of dashboard after sign-in
- DB rows (3 SELECT statements)
- Browser cookie inspector showing session cookie attributes
- `curl http://localhost:8000/api/auth/me --cookie cookies.txt` returns user info

## Notes

The very first user journey. If this is broken, nothing else matters.
