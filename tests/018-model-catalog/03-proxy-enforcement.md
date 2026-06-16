# 018 · Scenario 03 — Proxy enforces the catalog (the wall)

**Target:** the gateway proxy `/proxy/{anthropic,openai}/...` on luna-service.

Use a real tenant token (`lsv1-…`) for a test agent. cURL the proxy directly so we
exercise enforcement independent of Luna.

## Steps

1. **In-catalog model passes.** POST `/proxy/anthropic/v1/messages` with
   `{"model":"claude-opus-4-6", ...}` and the tenant token in `x-api-key`.
   → forwarded upstream (200, or the provider's own error — NOT our 404).
2. **Off-catalog model is blocked.** Same call with
   `{"model":"claude-3-opus-20240229"}` (not in catalog).
   → **404** from us, body `{"error":{"type":"not_found",...}}`, **before** any
   upstream call (no pool key spent — confirm via no `last_used_at` bump / logs).
3. **Alias resolves.** `{"model":"opus"}` (alias of `claude-opus-4-6`).
   → passes the gate (not 404).
4. **BYOK is not gated.** Repeat step 2 with a real provider key (not an `lsv1-`
   token) in the auth header → forwarded as-is (no catalog 404 from us).
5. **OpenAI path.** POST `/proxy/openai/chat/completions` with an off-catalog
   `{"model":"gpt-3.5-turbo"}` → 404; with `{"model":"gpt-4o"}` → passes.
6. **Embedding passes.** `/proxy/openai/embeddings` with
   `{"model":"text-embedding-3-small"}` → passes (memory must keep working).

## Pass

- Off-catalog managed calls 404 before upstream; in-catalog + alias pass; BYOK
  bypasses; embeddings pass.

## Fail

- Off-catalog reaches upstream (key spent) or returns a non-404; alias rejected;
  BYOK gated; embeddings 404'd.
