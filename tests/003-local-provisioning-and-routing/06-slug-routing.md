# Scenario 06 — Slug routing: /alice goes to Alice's Luna

## Preconditions

- Alice has a running Luna
- Bob has a running Luna

## Scenario

1. As Alice (logged in), navigate to `http://localhost:8000/alice` → should show Alice's Luna
2. As Alice (still logged in), navigate to `http://localhost:8000/bob` → should be denied (see scenario 07)
3. Sign out and sign in as Bob
4. Navigate to `http://localhost:8000/bob` → should show Bob's Luna
5. Navigate to `http://localhost:8000/alice` → should be denied

## Expected Behavior

- Each user can navigate to their own slug and see their own Luna
- The URL is the user-facing identifier for "which Luna am I in"
- API calls within the chat use `/alice/api/...` and route to Alice's Luna container

## Fail Conditions

- ❌ Alice navigating to `/alice` lands on Bob's Luna (catastrophic routing bug)
- ❌ `/alice/api/conversations` returns Bob's conversations
- ❌ Trailing slash inconsistency breaks routing (`/alice` works but `/alice/` doesn't, or vice versa)
- ❌ Path traversal attempts work (e.g., `/alice/../bob`)

## Verify

- Network tab in both sessions shows requests routed to correct Luna container (check internal URL or header)
- Container logs: Alice's Luna only sees Alice's user header, Bob's only sees Bob's

## Notes

The router is the most security-sensitive piece in the control plane. Any bug here is a data leak waiting to happen.
