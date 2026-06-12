# 014 — Tenant Isolation: test scenarios

Two groups:

**Local/unit:** `cloud/tests/test_tenant_isolation.py` — provisioner v2 SQL
flow (mocked + against a throwaway Postgres), per-agent proxy secret
derivation, env construction.

**Adversarial dojo (production, run from INSIDE a tenant machine):** the
attacker is a tenant. Use `fly ssh console` (or machine exec) on one agent's
machine and attempt to escape. Scenarios 01–07 below.

| # | Scenario | Expects |
|---|----------|---------|
| 01 | own-db-full-control | Agent connects to its own DB, sees only its tables, can create/drop |
| 02 | other-db-denied | Connecting to another agent's DB fails |
| 03 | control-db-denied | Connecting to lunatenants (shared/control DB) fails |
| 04 | catalog-blindness | pg_database shows names only; no other tenant's tables/schemas visible |
| 05 | cross-machine-forgery | Forged trusted-proxy request to another machine fails auth |
| 06 | normal-operation | Chat + gateway LLM call + usage metering still work after migration |
| 07 | reprovision-rotation | Re-provisioning rotates DB password; machine reconnects; data intact |
