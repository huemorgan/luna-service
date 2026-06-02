# Scenario 05 — Account slug uniqueness collision

## Preconditions

- Fresh DB
- Stub identity provider has TWO test users:
  - `alice@example.com` (display name "Alice")
  - `alice@other.com`   (display name "Alice")

Both would naturally generate the slug `alice`.

## Scenario

1. Sign in as `alice@example.com` → account created with slug `alice`
2. Sign out
3. Sign in as `alice@other.com` → second account created

## Expected Behavior

- Second account gets a deduplicated slug — `alice-2`, `alice2`, or `alice-<6-char-id>` (any deterministic, URL-safe scheme is fine)
- Both users land successfully on their respective dashboards
- Slug visible on dashboard for the second user is the deduplicated one
- DB: `accounts.slug` has UNIQUE constraint enforced; both rows exist with distinct slugs

## Fail Conditions

- ❌ Second sign-in fails with constraint violation surfaced as 500
- ❌ Second account overwrites or merges with first (data loss)
- ❌ Both accounts end up with empty/null slug
- ❌ Slug contains characters that break the URL routing (`@`, `.`, spaces, etc.)

## Verify

- DB shows two accounts with distinct slugs
- Each user's dashboard shows the correct slug
- Hit `http://localhost:8000/<slug-1>` and `http://localhost:8000/<slug-2>` → each resolves to the right account

## Notes

A surprising fraction of platforms fail this. Common bug: just appending `-1` deterministically — works for the first collision, breaks on the third.
