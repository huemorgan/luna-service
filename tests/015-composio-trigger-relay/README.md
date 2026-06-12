# 015 — Composio Trigger Relay: test scenarios

**Local/unit:** `cloud/tests/test_relay.py` — Standard Webhooks sign/verify,
relay secret derivation, ingress route behavior (403/401/202/dedupe),
tenant resolution, forwarder retry/dead-letter state machine, gateway
response capture, provisioning env injection.

**Dojo (local stack, LLM-driven):** run against `docker-compose.local.yml`
(control plane on :8100, docker-local Luna agents). The "Composio cloud" role
is played by `dev/sign_composio_event.py`. Set
`CLOUD_COMPOSIO_WEBHOOK_SECRET` on the control plane before running.

| # | Scenario | Expects |
|---|----------|---------|
| 01 | signed-delivery-end-to-end | Signed POST → 202 → forwarder delivers to the mapped agent machine with valid relayed signature |
| 02 | forged-and-unconfigured | Bad signature → 401, no delivery row; secret unset → 403 |
| 03 | unroutable-event | Unknown connected account → row status=unroutable, nothing forwarded |
| 04 | retry-and-recovery | Agent container stopped → retries with backoff; container started → delivered |
| 05 | admin-visibility | Admin UI shows deliveries + account links; manual link CRUD works |
| 06 | chat-unaffected | Freshly provisioned agent has LUNA_COMPOSIO_WEBHOOK_SECRET in env and normal chat still works (live walkthrough) |
