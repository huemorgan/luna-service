# Scenario 13 — Provisioning idempotency

## Preconditions

- Fresh DB
- Stub identity for Alice

## Scenario

Simulate a control-plane crash mid-provisioning:

1. Add a debug toggle to control plane: `CLOUD_PROVISION_CRASH_AT=after_schema` (crashes deliberately after creating the schema but before creating the container)
2. Sign in as Alice → provisioning starts → control plane crashes
3. Restart control plane
4. Sign back in as Alice
5. Observe what happens

Now do the same with `CLOUD_PROVISION_CRASH_AT=after_container_create` (container exists but agent row not finalized).

## Expected Behavior

- On retry (next sign-in or status poll), provisioning resumes from where it left off
- Final state is correct in both cases:
  - One schema, one container, one agent row, status=`running`
- No duplicates of anything
- No "schema already exists" or "container name in use" errors crashing the retry

## Fail Conditions

- ❌ Retry crashes due to existing resources
- ❌ New schema/container created alongside the orphaned one
- ❌ User stuck on provisioning screen forever
- ❌ Agent row left in inconsistent state (e.g., status=`provisioning` permanently after both crash sims)

## Verify

- DB: 1 row, 1 schema, 1 container after recovery
- Control plane logs show resumption logic firing ("schema exists, skipping", "container exists, checking health")

## Notes

Crashes happen. Servers restart. Network blips. Provisioning code must be safe to call any number of times. If it's not, fix it now — debugging "stuck provisioning" in production is the worst.
