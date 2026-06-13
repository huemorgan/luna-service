# Plan 015 — Composio Trigger Relay

Deliver external Composio trigger events to the right tenant Luna machine,
signed, queued, and observable. This is "the wrapper" side of Luna plan
`007.003-composio-hooks` (see its PLAN.md and our RECOMMENDATION.md in the
same folder) — one Composio webhook subscription for the whole managed
project, relayed per-tenant with per-tenant secrets.

```
Composio ──(Standard Webhooks, our secret)──▶ POST /api/webhooks/composio
   1. verify HMAC at the edge (CLOUD_COMPOSIO_WEBHOOK_SECRET)
   2. resolve agent from composio_account_links (never trust payload labels)
   3. enqueue into relay_deliveries (outbox, status=pending)
   4. background forwarder: re-sign with the agent's derived relay secret,
      fresh timestamp, preserved webhook-id → POST to the machine's
      /api/p/plugin-connectors/events/composio; retry w/ backoff; dead-letter
```

## Contract with Luna (from 007.003)

- Tenant ingress: `POST {machine}/api/p/plugin-connectors/events/composio`
- Standard Webhooks headers: `webhook-id`, `webhook-timestamp`,
  `webhook-signature` = `v1,base64(HMAC-SHA256(secret, "{id}.{ts}.{body}"))`
- Machine env: `LUNA_COMPOSIO_WEBHOOK_SECRET` (per-agent relay secret)
- Fresh timestamp at forward time; original `webhook-id` preserved
- Luna releases the verifier on its own schedule. Until then current images
  accept the POST unsigned — we inject the env var and sign NOW so the moment
  a machine updates to the verifier release, verification turns on seamlessly.

## Phases

### Phase A — relay core (`cloud/relay/`)

- `standard_webhooks.py`: `sign(...)` and `verify(...)` for the Standard
  Webhooks scheme. Constant-time compares, ±300 s tolerance, multi-signature
  header support, `v1,` prefix. Shared by ingress (verify Composio) and
  forwarder (sign for tenant).
- `secrets.py`: `derive_relay_secret(root, agent_id)` — same HKDF-style
  derivation as `cloud/runtime/proxy_secret.py` with info label
  `luna-composio-relay-v1:{agent_id}`. Root = `CLOUD_TRUSTED_PROXY_SECRET`.
  Nothing stored; control plane recomputes.
- Models (in `cloud/db/models.py`, created by lifespan `create_all`):
  - `composio_account_links`: `connected_account_id` PK, `agent_id` FK,
    `app_name`, `source` (gateway|admin), `created_at`, `last_seen_at`.
  - `relay_deliveries`: id, `webhook_id`, `agent_id` nullable,
    `connected_account_id`, `status` (pending|delivered|dead|unroutable|
    rejected), `attempts`, `next_attempt_at`, `last_status_code`,
    `last_error`, `body` (bytes/text, ≤200 KB), `created_at`, `delivered_at`.
    Index on (status, next_attempt_at).

### Phase B — ingress endpoint

`cloud/api/relay_routes.py` → `POST /api/webhooks/composio`:

1. 200 KB body cap (413 above).
2. No `CLOUD_COMPOSIO_WEBHOOK_SECRET` configured → 403 (default-deny, same
   posture we asked Luna for).
3. Verify signature over raw body BEFORE parsing JSON → 401 on failure.
4. Dedupe on `webhook-id` (existing delivery row → 200, no new row).
5. Extract `connected_account_id` from the payload (Composio payload shapes
   vary; tolerant extractor looks for `connected_account_id` /
   `connectedAccountId` / nested under `data`/`payload`).
6. Mapping hit → row status=pending agent_id set. Miss → row
   status=unroutable (kept for visibility, never broadcast). Always 202.

### Phase C — tenant mapping capture

- Gateway capture: in `gateway_proxy.py`'s managed flow for
  `service_slug == "composio"`, accumulate the response body (cap 1 MB)
  alongside the existing `UsageScanner`, and on stream close hand it to
  `cloud/relay/capture.py` — extracts connected-account ids from
  connectedAccounts-shaped JSON and upserts `composio_account_links` rows for
  that agent. Capture failures are logged, never break the response (same
  rule as metering).
- Admin CRUD: `GET/POST/DELETE /api/admin/relay/links` for manual mapping
  fixes (admin-gated, audit-logged like other admin routes).
- Reconciliation job against Composio's API: deferred (noted in Decisions).

### Phase D — forwarder worker

`cloud/relay/forwarder.py`, asyncio task started in `main.py` lifespan
(skipped under tests):

- Poll `relay_deliveries` for `status=pending AND next_attempt_at <= now`
  (small batch, oldest first).
- Per delivery: derive the agent's relay secret, sign
  `{webhook_id}.{fresh_ts}.{body}`, POST to
  `{agent.internal_url}/api/p/plugin-connectors/events/composio` with the
  three Standard Webhooks headers + `fly-force-instance-id` (same machine
  pinning as the user proxy) + `x-luna-proxy-secret` (so current hosted
  images that gate all routes behind the trusted-proxy check accept the call;
  harmless later, it's per-agent anyway).
- 2xx → delivered. Connection error / 5xx → attempts+1, exponential backoff
  (30 s · 2^n, cap 15 min), wake stopped machines through the existing
  auto-wake helper, dead-letter after 10 attempts. 4xx (except 408/429) →
  dead immediately (signature rejected / bad request won't heal by retrying).

### Phase E — provisioning + env

- `_provision_core` (workflow.py): add `LUNA_COMPOSIO_WEBHOOK_SECRET` =
  derived relay secret to the machine env (both runtimes get it via
  `AgentSpec.llm_keys`-style env dict — piggyback on `build_gateway_env`
  output dict).
- `.env.example`: document `CLOUD_COMPOSIO_WEBHOOK_SECRET` (from Composio
  dashboard → webhook subscription secret; absent in dev = ingress 403s).

### Phase F — admin visibility

- `GET /api/admin/relay/deliveries?limit=N` — recent deliveries with status,
  attempts, agent slug.
- Minimal admin UI: "Webhook Relay" section (deliveries table + links table)
  on the admin area. Table only, no charts.

### Phase G — dev harness + tests

- `dev/sign_composio_event.py`: signs a sample Composio payload with any
  secret and POSTs it (to the relay ingress or directly to a machine).
  Doubles as the E2E fixture and the self-hoster curl example.
- Unit tests `cloud/tests/test_relay.py` (patterns from test_gateway.py).
- Dojo scenarios in `tests/015-composio-trigger-relay/` (see folder README).

## Decisions / deferred

| Topic | Decision |
|---|---|
| Composio subscription mgmt | Manual in Composio dashboard; secret pasted into Render env. One project, one subscription. |
| Relay secret rotation | Derived from `CLOUD_TRUSTED_PROXY_SECRET`; rotating that root rotates everything (machines get new values on re-provision). Per-secret-version overlap deferred until Luna ships multi-secret verify. |
| Per-tenant rate limiting | Deferred — outbox already absorbs bursts; add limiter when real traffic exists. |
| Composio API reconciliation job | Deferred — gateway capture + admin CRUD cover current scale. |
| Payload retention | Delivered/dead rows keep body for 30 days (cleanup job deferred; volume is tiny). |
| Luna-side verification | Not a dependency. We sign from day one; Luna enforces when their 007.003 ships. |

## Definition of done

- Signed Composio-style POST to `/api/webhooks/composio` lands on the mapped
  local Luna machine with valid Standard Webhooks headers (verified by
  re-checking the signature with the derived secret at the receiving end).
- Bad signature → 401, no row. No secret → 403. Unknown account → unroutable.
- Machine down → retries with backoff, delivers when it's back, dead-letters
  past the cap.
- Admin can see deliveries + manage links.
- Unit tests green; dojo scenarios pass against the local stack; live
  walkthrough (chat with a local Luna) unaffected.
