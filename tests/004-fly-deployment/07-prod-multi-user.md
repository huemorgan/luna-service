# Scenario 07 — Multi-user production isolation

## Preconditions

- Production deployed
- Two real Google accounts available for testing (test1@..., test2@...)

## Scenario

Same shape as phase 003 scenario 05, but on production:

1. Sign up test1, provision Luna, store a secret memory
2. Sign up test2 (different browser / incognito), provision Luna, ask Luna about test1's secret memory
3. Verify isolation
4. Check Render tenant DB: two schemas, two role grants, no cross-access
5. Check Fly: two Machines, two different IDs, two different env vars

## Expected Behavior

Identical to phase 003 scenario 05 — but verifying production cloud infrastructure (Render Postgres + Fly) maintains isolation, not just Docker.

## Fail Conditions

Same as phase 003 scenario 05, with added severity (production data).

## Verify

- Render dashboard or `psql` connection showing both schemas in the tenant Postgres
- Fly dashboard showing both Machines with distinct configs
- Direct spot-check: connect to the tenant DB as test1's scoped role → can't see test2's schema (PostgreSQL permission denied)

## Notes

Production retest of the most critical security property. If this ever fails in production, **immediately** suspend signups and investigate.
