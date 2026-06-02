# Scenario 02 — Returning user sign in

## Preconditions

- Scenario 01 has been run for Alice (user/account/membership rows exist)
- Browser cleared of cookies

## Scenario

1. Open `http://localhost:8000/`
2. Click "Sign in with Google"
3. Choose Alice (same account as scenario 01)
4. Land on dashboard
5. Compare to scenario 01

## Expected Behavior

- Lands on dashboard, same account as before
- DB state:
  - Still 1 row in `users`, `accounts`, `memberships` (no duplicates)
  - `users.last_login_at` updated to NOW
  - `accounts.id` is the **same** as last time
- Same account slug, same UI

## Fail Conditions

- ❌ Duplicate user row created
- ❌ Duplicate account row created
- ❌ Lands on a different account
- ❌ `last_login_at` not updated

## Verify

- DB: count of users/accounts is still 1
- DB: `last_login_at` newer than `created_at`
- Screenshot of dashboard (should look identical to scenario 01)

## Notes

Trivial but critical — proves we upsert by `google_sub`, not create-every-time.
