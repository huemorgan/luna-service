# Scenario 09 — Google OAuth failure path (google-only)

## Preconditions

- `CLOUD_IDENTITY_PROVIDER=google`
- Real Google OAuth configured

## Scenario

Three failure variants — test all three:

### A. User denies consent

1. Click "Sign in with Google"
2. On Google's consent screen, click "Cancel" / "Deny"

**Expected:** redirected back to landing with a friendly error toast: "Sign-in cancelled. Try again." NOT a 500. NOT a blank page.

### B. State token mismatch (CSRF protection)

1. Initiate OAuth flow, copy the Google URL
2. Mutate the `state` query param to a random string
3. Submit (using browser address bar or curl)

**Expected:** server detects state mismatch → returns 400 with clear error. User redirected to landing. NOT logged in.

### C. Email not verified

1. Sign in with a Google account whose `email_verified` claim is false (hard to set up — may skip or simulate via stub)

**Expected:** server rejects, shows "Please verify your email with Google first." Not logged in.

## Fail Conditions

- ❌ Any of the three returns 500 / stack trace visible
- ❌ User ends up partially authenticated (session set but no DB row, or vice versa)
- ❌ CSRF bypass succeeds (state token not checked)

## Verify

- DB unchanged for all three (no orphan users/sessions)
- Visible UI feedback for each failure mode

## Notes

OAuth failure paths are where security bugs hide. Always test the cancel button.
