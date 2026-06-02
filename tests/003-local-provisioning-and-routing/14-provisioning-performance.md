# Scenario 14 — Performance: provision in < 30s

## Preconditions

- Fresh DB
- Luna image already pulled (`docker images` shows `luna-hosted:dev-001`)

## Scenario

1. Note current timestamp
2. Sign in as a new user
3. Note timestamp when chat UI becomes interactive
4. Calculate: total provisioning time

Repeat 5 times with 5 different users to get a distribution.

## Expected Behavior

- p50 < 20 seconds
- p95 < 30 seconds
- p99 < 45 seconds (one outlier acceptable)
- No regressions over time as more users provision

## Fail Conditions

- ❌ p50 > 30s — provisioning too slow, breaks the "minute" promise
- ❌ Time grows with each provision (something not getting cleaned up)
- ❌ Any single provision > 60s

## Verify

- Wall-clock times recorded
- Control plane logs show per-step timings: schema creation, vault key derive, container create, container healthcheck
- Identify the slowest step to optimize

## Notes

A 30-second wait is the boundary between "wow that was fast" and "this thing is broken." Measure, don't guess.

Slowest step on a laptop is typically:
- Docker container startup: ~3s
- Luna's Python imports + Alembic migrations: ~5-10s
- Plugin discovery + LLM provider health checks: ~3s

If any step takes 10+ seconds, dig in.
