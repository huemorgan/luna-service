# 047 — Approval card resilience (stuck "Approval Needed" on 500)

## Incident (2026-07-19, RayLa)
- Owner clicked "Just this once" on a batched `trigger_delete` approval (2 items, Scheduler plugin). Both POSTs to `/api/p/plugin-approvals/{id}/approve` returned 500. The card showed `2/2 failed: Error: 500` and could not be dismissed — the X button is `reject`, which hits the same failing API. It resolved "after a long long while" (1 approved / 2 rejected chips eventually rendered).

## Root cause (server)
- Agent machines (Fly, sjc) reach Postgres (Render) with **NullPool** — a fresh TLS connection per request (`luna/luna/data/__init__.py:53-59`; normal connects log 300–500 ms). At 14:11:50Z starla logged an asyncpg connection-establishment failure inside `list_approvals` → unhandled → 500. Same failure mode explains the approve/reject 500s: transient connect exhaustion/timeout (per-tenant role cap 20 conns; ~29 machines share the cluster; scheduler firing + UI polling + turn activity burst).
- `approve_approval`/`reject_approval` only map KeyError→404, ValueError→409 (`luna/plugins/plugin_approvals/routes.py:686-773`). DB connect errors surface as raw 500s.

## Why the card stayed stuck (client)
`luna/ui/src/views/InlineApprovalCard.tsx`:
- On failure, `setError` + `setBusy(false)` — the card just sits there. Retry = clicking again; no auto-retry, no backoff.
- No status re-poll: if the decision actually landed server-side (or lands later), the card doesn't learn it until the surrounding panel refetches. `decided` only updates via parent re-hydration.
- The X is a reject API call, not a local dismiss — when the API is down, the user cannot even collapse the card.

## Proposed fixes (luna repo — NOT the submodule checkout here)
1. **UI: reconcile before erroring.** After a failed approve/reject, GET `/{id}` for each request; if status != pending, treat as decided and collapse (the server may have committed despite the failed response). Show "checking…" state.
2. **UI: retry with backoff.** On 5xx, auto-retry the decision 2–3 times (1s/3s/8s) before surfacing the error; keep the buttons enabled after final failure.
3. **UI: local dismiss.** X should collapse the card locally (it stays in the Approvals panel pending tab); rejection stays an explicit button. Never leave the user with an unclosable box.
4. **UI: poll while errored.** While an error is displayed, poll `/{id}` every ~10s so an eventual server-side resolution (owner action elsewhere, TTL expiry) collapses the card without a reload — this is exactly the "long long while" Roy saw; make it minutes→seconds.
5. **Server: map DB unavailability to 503 + retry-once.** Wrap `approvals.decide` calls: retry once on connection-establishment errors, else raise 503 (not 500) so the client can distinguish "temporarily down, retry" from a bug.
6. **Infra (option, separate decision): enable `LUNA_DB_POOL=1` on agent machines** if the serve entrypoint is single-loop — kills the per-request connect tax and most transient connect failures. Needs sizing: N machines × pool_size under cluster max_connections (tenant roles capped at 20).

## Non-goals
- The Scheduler `trigger_delete` approval flow itself worked as designed; nothing to change there.
