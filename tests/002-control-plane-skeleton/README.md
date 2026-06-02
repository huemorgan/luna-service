# Phase 002 — Test Scenarios

Dojo-style scenarios for the control plane: Google auth, session, accounts. NO Luna integration yet — the "Your Luna" panel is a placeholder.

## Setup (Once)

```bash
cd cloud
make cloud-up  # starts Postgres, runs migrations, starts FastAPI + Vite
```

Verify:
- `http://localhost:8000` returns the landing page
- `http://localhost:8000/api/auth/me` returns 401 (not logged in)

Two modes for running scenarios:
- **Stub identity** (`CLOUD_IDENTITY_PROVIDER=stub`) — fast, no real Google OAuth needed
- **Google identity** (`CLOUD_IDENTITY_PROVIDER=google`) — slower, real OAuth (use a test Google account)

Scenarios should be run in **both modes** unless explicitly marked stub-only or google-only.

## Scenarios

| # | Scenario | File |
|---|----------|------|
| 01 | First-time user sign in | `01-first-signin.md` |
| 02 | Returning user sign in | `02-returning-signin.md` |
| 03 | Sign out clears session | `03-signout.md` |
| 04 | Unauthenticated → redirected to landing | `04-unauth-redirect.md` |
| 05 | Account slug uniqueness collision | `05-slug-collision.md` |
| 06 | Session persists across browser refresh | `06-session-persistence.md` |
| 07 | Multi-tab consistency | `07-multi-tab.md` |
| 08 | Dashboard shows placeholder Luna state | `08-dashboard-placeholder.md` |
| 09 | Google OAuth failure path | `09-oauth-failure.md` (google-only) |
| 10 | Render staging end-to-end smoke | `10-staging-smoke.md` (staging-only) |
