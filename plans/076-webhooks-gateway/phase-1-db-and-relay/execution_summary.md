# Phase 1 — execution summary

Commit: `c7a3609` (local; pushed with phase 4 — a push to main autodeploys Render,
so phases 1–3 batch into one deploy).

## What shipped
- `cloud/db/models.py`: `WebhookEndpoint` model (uuid PK, agent FK CASCADE, unique
  `hook_slug`, unique (agent_id, plugin, name), target_path, mode sync|queue,
  per-hook secret, enabled, delivery stats) and nullable `RelayDelivery.target_path`.
- `cloud/alembic/versions/0016_webhook_endpoints.py`: creates the table + column;
  reversible downgrade.
- `cloud/db/migrate.py`: `POST_BASELINE_COLUMNS["relay_deliveries"] = {"target_path"}`
  — relay_deliveries is a 0001-baseline core table; without this entry the legacy-DB
  fingerprint check would refuse to adopt existing databases. `webhook_endpoints` was
  deliberately NOT added to CORE_TABLES (either copy).
- `cloud/relay/forwarder.py`: delivers to `delivery.target_path or EVENTS_PATH`; the
  composio path is now just the legacy default.

## Verified
- `cloud/tests/test_relay.py`: two new tests — `test_custom_target_path_used`,
  `test_null_target_path_falls_back_to_composio`. File: 36 passed.
- Full-suite regression check deferred to end of phase 2 (same working tree).

## Deviations / learnings
- None from PHASE.md. The POST_BASELINE_COLUMNS requirement was anticipated in
  phase-0 prep and confirmed: migrate.py documents that every migration touching a
  CORE_TABLES table must register its columns there.

## Reassessment of remaining phases
No changes. Phase 2 proceeds as planned; forwarder needed no interface change for
queue-mode hooks (ingress will set target_path on insert).
