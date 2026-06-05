# Scenario 01 — No Login Screen in Production

## Preconditions

- luna-service deployed to Render.com at `luna.com.ai`
- At least one agent provisioned with status "running"
- User authenticated via Google OAuth on luna.com.ai dashboard
- Agent accessible at `https://luna.com.ai/a/<agent-slug>/`

## Scenario

1. Open `https://luna.com.ai` — log in via Google OAuth if needed
2. From the dashboard, note the agent slug
3. Navigate to `https://luna.com.ai/a/<agent-slug>/` in the same browser session
4. Observe the initial page load
5. Wait up to 10 seconds for the page to fully load
6. Check the DOM for any login/signup form elements

## Expected Behavior

- Step 4: Luna UI loads — the "waking up" splash may flash briefly
- Step 5: Chat interface appears directly — no login screen, no signup form
- Step 6: DOM contains NO `<input type="password">`, NO "Sign in" button, NO "Sign up" button, NO username/password form

## Fail Conditions

- Login screen appears (username + password form)
- Signup screen appears (create account form)
- "Welcome back" text visible (Login component heading)
- Any password input in the DOM at any point
- Page stuck on "waking up" splash for more than 15 seconds
- Error message about authentication

## Verify

- Screenshot of the loaded page showing chat interface (not login)
- DOM snapshot confirming no password inputs exist
- Call to `/a/<agent-slug>/api/auth/status` returns `{"trusted_proxy": true, ...}`
- Call to `/a/<agent-slug>/api/auth/proxy-login` (POST) returns a valid token

## Notes

The fix requires Luna to support `LUNA_AUTH_MODE=trusted_proxy` env var.
When set, `/api/auth/status` returns `trusted_proxy: true` and the UI auto-calls
`/api/auth/proxy-login` to get a JWT without showing login/signup screens.
The proxy secret is validated server-side via `X-Luna-Proxy-Secret` header.
