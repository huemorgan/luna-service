# Scenario 04 — Unauthenticated → redirected to landing

## Preconditions

- Fresh browser, no cookies

## Scenario

Hit each of these in turn:

1. `http://localhost:8000/dashboard`
2. `http://localhost:8000/alice` (placeholder — no agent yet but the route should exist)
3. `http://localhost:8000/api/accounts/me`
4. `http://localhost:8000/api/agents`

## Expected Behavior

| URL | Result |
|-----|--------|
| `/dashboard` | Redirect to `/` (or render landing with login CTA) |
| `/alice` | Redirect to `/` (or to `/?next=/alice` to bounce after login) |
| `/api/accounts/me` | 401 |
| `/api/agents` | 401 |

## Fail Conditions

- ❌ Any of the UI routes renders the dashboard / chat UI without auth
- ❌ API endpoints return 200 with data
- ❌ API endpoints return 500
- ❌ Redirect URL is wrong (e.g., to a Google URL)

## Verify

- Browser network tab for each navigation
- `curl -i` output for each API endpoint

## Notes

Standard auth gating. Don't ship a dashboard that's accessible without auth.
