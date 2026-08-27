# Phase 1 — DB model, migration 0016, forwarder generalization

## Scope
- `cloud/db/models.py`: new `WebhookEndpoint` table; nullable `target_path` on
  `RelayDelivery`.
- `cloud/alembic/versions/0016_webhook_endpoints.py`: create table + add column.
- `cloud/db/migrate.py`: `POST_BASELINE_COLUMNS["relay_deliveries"] = {"target_path"}`
  (relay_deliveries is in the 0001 CORE_TABLES baseline — learned in phase 0 prep;
  without this every legacy DB fingerprint check would refuse to migrate).
  `webhook_endpoints` itself stays OUT of CORE_TABLES (both copies).
- `cloud/relay/forwarder.py`: deliver to `delivery.target_path or EVENTS_PATH`.

## WebhookEndpoint columns
id uuid PK; agent_id FK agents.id CASCADE; hook_slug Text unique (URL token);
name Text; plugin Text; target_path Text; mode Text default 'sync';
secret Text; enabled bool default True; created_at; last_delivery_at nullable;
delivery_count int default 0; last_status_code int nullable.
Unique index on (agent_id, plugin, name) for idempotent upsert.

## Verification
- New unit test: forwarder posts to a custom target_path when set, falls back to
  the composio EVENTS_PATH when NULL (extend the fake-transport pattern in
  test_relay.py).
- Full suite stays at baseline (1 pre-existing billing failure only).
- Alembic migration runs clean on an empty postgres (verified in phase 4 deploy;
  locally we rely on the suite's create_all + a syntax check via alembic's
  offline compile if feasible).
