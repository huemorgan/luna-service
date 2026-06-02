# Scenario 10 — Render staging end-to-end smoke (staging-only)

## Preconditions

- Phase 002 deployed to Render at `https://luna-service-control-staging.onrender.com`
- Google OAuth app has the staging callback URL added
- Render Postgres provisioned and migrations run

## Scenario

1. Open `https://luna-service-control-staging.onrender.com/` in a fresh browser
2. Verify TLS (green padlock, no warnings)
3. Verify landing page renders correctly (no broken CSS, no missing images)
4. Click "Sign in with Google"
5. Complete OAuth with a real test Google account
6. Land on staging dashboard
7. Inspect: user info, account info, Luna placeholder
8. Sign out
9. Sign back in

## Expected Behavior

- All scenarios from 01-08 work identically against staging
- No CORS errors
- No mixed-content warnings
- HTTPS everywhere (no http:// in any links)
- Response times reasonable (< 2s for initial load, < 500ms for API calls)

## Fail Conditions

- ❌ Any TLS warning
- ❌ Any CORS error in console
- ❌ Any difference in behavior vs. local
- ❌ Render service health checks failing
- ❌ Postgres connection errors in Render logs

## Verify

- Browser screenshot showing padlock + staging URL
- Render dashboard shows service "live" status
- Render logs show successful requests, no errors
- Sentry (if configured) shows no errors

## Notes

Catches the "works on my machine but not in production" class of bugs. Easy ones: missing env vars, wrong callback URLs, secure-cookie flag set in dev but cookies don't travel over local HTTP.
