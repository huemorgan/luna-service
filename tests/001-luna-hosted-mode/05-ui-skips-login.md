# Scenario 05 — UI hides login screen in trusted mode

## Preconditions

- Local stack up, Luna in trusted-proxy mode

## Scenario

1. Open `http://localhost:8080/` in a fresh incognito window (no cookies)
2. Observe what loads
3. Check the URL bar — is it `/login` or `/signup` at any point?
4. Check the page DOM — is there any `<form>` for email/password? Any "Sign in" button?
5. Hit `http://localhost:8080/login` directly — what happens?
6. Hit `http://localhost:8080/signup` directly — what happens?

## Expected Behavior

- Step 2: chat UI loads immediately, no login flash
- Step 3: URL stays at `/` or `/chat`, never visits login/signup
- Step 4: NO login form, NO signup form, NO password fields in DOM
- Step 5: `/login` either 404s, redirects to `/`, or shows a "managed externally" message
- Step 6: `/signup` same — should not present a signup form

## Fail Conditions

- ❌ Login screen flashes even briefly (means UI hasn't checked auth mode)
- ❌ A password input is anywhere in the DOM
- ❌ User can navigate to `/login` and submit something

## Verify

- Screenshot of initial page load
- DOM snapshot proving no password inputs exist
- Test direct navigation to `/login` and `/signup`
- Call `GET /api/auth/mode` → should return `{"mode": "trusted_proxy"}`

## Notes

This is a subtle bug to introduce — the API enforces trust mode, but the UI still ships login forms. Result: users see login forms that don't work. The UI must check `/api/auth/mode` and adapt.
