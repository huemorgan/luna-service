# Scenario 07 — User B cannot access User A's URL

## Preconditions

- Alice and Bob both have Lunas

## Scenario

While logged in as Bob, hit each of these:

1. `http://localhost:8000/alice` (UI)
2. `http://localhost:8000/alice/api/conversations`
3. `http://localhost:8000/alice/api/conversations/<known-conversation-id-from-alice>`
4. `http://localhost:8000/alice/api/auth/me`

Then sign Bob out, log in as Alice, hit `http://localhost:8000/bob/api/conversations`.

## Expected Behavior

All of these → **403 Forbidden** (not 401, not 404 — Bob IS authenticated, just not authorized for Alice's resources).

A friendly error page or JSON response says "You don't have access to this account."

## Fail Conditions

- ❌ Any of the requests returns 200 with Alice's data
- ❌ Returns 404 (gives away that the path doesn't exist for them — but more importantly hides the auth check failure)
- ❌ Returns 500
- ❌ Returns 401 (means we didn't check membership, only authentication)
- ❌ Bob can access Alice's Luna container directly via Docker network (separate issue; verify network isolation if Docker compose puts them on different networks)

## Verify

- Status codes via `curl -i` (with Bob's session cookie)
- Audit log: should contain entries for these denied attempts (for security monitoring)

## Notes

This isn't paranoia — users typo URLs, share screenshots, or are deliberately curious. The router must always check membership, not just session.
