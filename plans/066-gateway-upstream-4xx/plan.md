# Plan 066 — Gateway-side tracking of upstream LLM 4xx/5xx errors

## Incident that exposed this
gpt-5.5 rejected a chat turn with `400 invalid_request_error: "Invalid 'tools':
array too long. Expected an array with maximum length 128, but got an array with
length 135 instead."` The user saw the raw error twice in chat; retrying couldn't
ever succeed. In Error Tracking this was invisible from the service side.

Today the only capture path for a provider 4xx is **agent-side**: luna core logs
`agent.stream_error` (ERROR) in `luna/agent/runtime.py`, and plugin-feedback's
root-logger handler forwards WARNING+ to `/api/agent/errors`. That path is
best-effort three times over: plugin-feedback must be in that image's plugin set,
the 500-char message clamp usually cuts the traceback before the actual provider
error line, and the fingerprint groups as a generic `agent_report`.

Meanwhile the **gateway proxied the exact failure** — it knows the service, the
model, the status code, and the full provider error body — and recorded only a
non-billable `usage_event` (`cloud/api/gateway_proxy.py:187`). The only
`record_error_event` call in the gateway is `gateway_auth` (invalid tenant
token). `cloud/api/proxy.py` already records `proxy_502` for the machine proxy;
the gateway is the one blind spot, and it is the single choke point every tenant
LLM call passes through regardless of plugin set.

## Design

### 1. New kind `upstream_4xx` (+ reuse `http_5xx` for ≥500)
- Add `"upstream_4xx"` to `KINDS` in `cloud/observability/error_sink.py` and to
  the kind comment in `cloud/db/models.py`.
- Upstream `>= 500` responses (after the key-fallback retries in
  `gateway_proxy` are exhausted and the response actually streams to the
  client) use the existing `http_5xx` kind.

### 2. Capture point: the `finally` block of `_stream_response`'s `stream()`
`cloud/api/gateway_proxy.py` — same place `record_usage` already runs, i.e.
after the response has fully streamed; zero latency added to the client path.

- **Error-body tee**: when `resp.status_code >= 400`, accumulate chunks into a
  bounded `error_buf` (cap 2 KB), same pattern as `capture_composio`'s
  `capture_buf`. Error bodies are small JSON; the cap is a safety rail.
- **Model**: pass `model` into `_stream_response` — the caller already has
  `billing.canonical_model` (managed flow) and `_requested_model(body)` (BYOK);
  prefer canonical, fall back to requested, else `"-"`.
- In `finally`, after `record_usage`, when `status >= 400`:

  ```python
  await record_error_event(
      kind="upstream_4xx" if resp.status_code < 500 else "http_5xx",
      severity="warning" if resp.status_code == 429 else "error",
      source="service",
      message=f"{service_slug} upstream {resp.status_code} for model {model}: {excerpt}",
      route=f"/proxy/{service_slug}",
      agent_id=agent_id,
      context={
          "service": service_slug, "model": model,
          "status_code": resp.status_code, "attempt_number": attempt_number,
          "body": error_buf_text[:2048],
      },
  )
  ```

  `excerpt` = first ~300 chars of the body with whitespace collapsed (the
  provider `message` field is at the front of every major provider's error
  JSON, so the human-readable cause survives the clamp).
- Wrapped in its own `try/except` like the `record_usage` call — the response
  is already delivered; telemetry must never raise. (`record_error_event`
  itself never raises, but the tee/format code around it could.)

### 3. Grouping / storm behavior — already solved, just inherit it
- `compute_fingerprint` normalizes all numbers, so `length 135` vs `length 136`
  vs `128` collapse into one group; putting the **model in the message** makes
  groups per-service+model+error-shape — exactly the triage unit ("gpt-5.5
  tools-array overflow", "opus 429s").
- Per-fingerprint throttle (10/min) + drop-on-DB-failure in the sink cap the
  write load during a provider incident. A retry storm of the same 400 becomes
  one group with a climbing count — which plan 065's open/regressed status then
  triages.

### 4. What is deliberately NOT recorded
- Gateway-generated 4xx (missing credential 401, policy 403, off-catalog 404,
  budget 402): those are the gateway working as designed; `gateway_auth`
  already covers the one that means silent total failure.
- Upstream statuses in `_FALLBACK_STATUSES` that a second pool key then
  satisfies: only the response that actually reaches the client is recorded
  (the capture lives in `_stream_response`, which is only called on the final
  attempt — earlier attempts already log + `mark_key_failure`).
- No API keys, no auth headers, no request body in the event. Only the
  provider's error response body, which contains no tenant secrets.

### 5. UI
- Add `upstream_4xx` to the `KINDS` filter list in
  `cloud/ui/src/pages/admin/ErrorsPage.tsx`. Rows/chips/grouping all work
  as-is.

### 6. Tests (`cloud/tests/`, alongside existing gateway tests)
- Upstream 400 with JSON error body → one `error_events` row: kind
  `upstream_4xx`, severity `error`, message contains model + provider message,
  context carries status/model/body; usage row still written non-billable.
- Upstream 429 → severity `warning`.
- Upstream 500 (after fallbacks exhausted) → kind `http_5xx`.
- Upstream 200 → no error event.
- Error body larger than cap → excerpt/context truncated, no failure.
- `record_error_event` forced to raise → response still streams (contract).
- Same 400 repeated 20× fast → ≤ throttle-limit rows (sink throttle honored).

## Verification of the original incident (blocked, do first)
Could not confirm from this machine whether the July 31 gpt-5.5 400 was captured
agent-side: `scripts/pull-errors.py` needs `RENDER_API_KEY` (mints the admin
cookie via the Render API) and it isn't present in env or any local .env.
With the key available:

```
RENDER_API_KEY=… .venv/bin/python scripts/pull-errors.py --hours 72
grep -ril "array too long\|stream_error" errors/
```

Or in the admin UI: /admin/errors → status filter "All statuses" → search
`stream_error` / `array too long`. If nothing surfaces, that machine's plugin
set lacks plugin-feedback — which is exactly why this plan puts capture in the
gateway.

## Out of scope (follow-up, luna core)
The root defect: the agent shipped **135 tool definitions** to a provider that
caps at 128. Needs a luna-core plan — deterministic cap/prioritization of
registered tools per provider limit (and an `agent_report` when tools are
dropped) — otherwise every turn on that agent keeps failing no matter how well
we track it.

## Scope
~15 lines error_sink/models (new kind), ~40 lines gateway_proxy (tee + record +
model plumb-through), ~5 lines UI kinds list, ~100 lines tests. No migration —
`error_events` already fits. No luna/plugin changes.
