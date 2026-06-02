# Phase 003 — Test Scenarios

This phase is **the full MVP, locally**. These scenarios are the most important in the entire MVP — they verify that the platform actually works: signup provisions a real Luna, requests route correctly, and isolation holds.

## Setup (Once)

```bash
docker compose -f docker-compose.local.yml up -d
# Wait for: postgres, redis, control-plane all healthy
# Verify: http://localhost:8000 shows landing
```

Verify Docker socket is accessible to the control plane:
```bash
docker exec luna-service-control docker ps
# (control plane can list containers via mounted socket)
```

## Scenarios

| # | Scenario | File |
|---|----------|------|
| 01 | Signup provisions a Luna | `01-signup-provisions-luna.md` |
| 02 | Provisioning status screen polls and transitions | `02-provisioning-ux.md` |
| 03 | Land in chat, full conversation works | `03-end-to-end-chat.md` |
| 04 | Returning user lands on existing Luna | `04-returning-user.md` |
| 05 | Two users — full isolation | `05-multi-user-isolation.md` |
| 06 | Slug routing: /alice goes to Alice's Luna | `06-slug-routing.md` |
| 07 | User B cannot access User A's URL | `07-cross-account-block.md` |
| 08 | SSE streaming through proxy works | `08-sse-streaming.md` |
| 09 | Provisioning failure shows friendly error | `09-provisioning-failure.md` |
| 10 | Retry after provisioning failure works | `10-provisioning-retry.md` |
| 11 | Container restart preserves user data | `11-container-restart-persistence.md` |
| 12 | Vault key per-tenant uniqueness | `12-vault-key-isolation.md` |
| 13 | Provisioning idempotency | `13-provisioning-idempotency.md` |
| 14 | Performance: provision in < 30s | `14-provisioning-performance.md` |
| 15 | Full MVP walkthrough (end-of-phase smoke) | `15-mvp-walkthrough.md` |
