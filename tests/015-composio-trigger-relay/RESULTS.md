# 015 dojo results — 2026-06-13 (local stack)

Unit: `cloud/tests/test_relay.py` — 33 tests, all green (full suite 91 passed).

| # | Scenario | Result | Evidence |
|---|----------|--------|----------|
| 01 | signed-delivery-end-to-end | PASS | 202 → delivered, attempts 1, code 200; luna-bob log shows `POST /api/p/plugin-connectors/events/composio 200` and bus event `connector.gmail.new_gmail_message` |
| 02 | forged-and-unconfigured | PASS | wrong secret 401, headerless 401, stale timestamp 401 — zero rows created; CP restarted with secret unset → 403 |
| 03 | unroutable-event | PASS | 202 + status=unroutable, attempts stays 0, nothing forwarded; after admin link added, the next event delivered while the old row stayed unroutable |
| 04 | retry-and-recovery | PASS | bob stopped → pending, attempts 2, ConnectError, backoff visible in next_attempt_at; bob started → delivered on attempt 3, code 200 |
| 05 | admin-visibility | PASS | /admin/relay renders deliveries (color-coded delivered/pending/unroutable/dead) and links; Add Link via form worked, delete via trash icon worked; anon API access 401, non-admin 403 (unit) |
| 06 | chat-unaffected | PASS | bob re-provisioned: `LUNA_COMPOSIO_WEBHOOK_SECRET` in env matches HKDF derivation, distinct per agent; live chat through `/a/bob-my-luna/` streams, multi-turn memory intact (quoted first message verbatim), history survived reload |

## Issues found and fixed during the run

1. **Local image was stale (Luna 0.1.0)** — first forward got 405 from bob.
   Rebuilt `local-luna-luna:latest` from the current submodule using
   `docker/luna-hosted.Dockerfile`; re-provisioned bob → 0.08.002 with the
   connectors ingress → 200.
2. **Pre-existing local provisioning bug** — `_host_for_runtime` stripped
   `+asyncpg` for docker-local URLs after the host swap, so freshly
   provisioned machines crash-looped on `ModuleNotFoundError: psycopg2`
   (this is why luna-alice had been restart-looping for days). Fixed in
   `cloud/provisioning/workflow.py`; both local agents re-provisioned healthy.
3. **Local-only setup notes:** provisioning from the host needs
   `CLOUD_BASE_URL=http://luna-service-cp:8100` so machine env points at the
   CP container (default localhost:8100 is unreachable from inside the
   docker network), and the local gateway pool needed an anthropic key
   (added via the Key Registry admin API). Neither is a code defect.
