# 063 — model picker refresh: execution report

Date: 2026-07-31. Plan: `luna/plans/063-model-picker-refresh/PLAN.md`.

## Delivered

- **Luna core 0.54.002** (`b4bbd224`): model picker with agentic-work rankings, cost pips = price level (floor 1, no zero-pip rows), provider grouping (openai → anthropic → moonshot → xai → gemini) with hairline dividers, "recommended" tag removed from Opus. plugin-chat-ui pinned 0.2.0 (`5243db16`, fix `071fe2fa`).
- **Kimi K2.6 Agent Ops** (`kimi-k2.6`) added to service catalog + pricing; routed via moonshot gateway route.
- **Fleet plugin upgrade**: plugin-chat-ui → 0.2.0 on all 31 started tenants (29 upgraded, 2 already current, 0 failed). `nave-my-luna-2` skipped — machine stopped in pre-op snapshot, left stopped (machine states restored per snapshot).
- **Dojo browser test**: `luna/dojo/tests/063-model-picker-refresh/walkthrough.mjs` — **13/13 PASS** against prod `vaselin-gamer` through the CP proxy. Verified: 0.2.0 live, grouping/dividers (`openai>anthropic>moonshot>xai`, 3 dividers), Kimi K2.6 present with Quality 4 / Speed 3 / Cost 1, Opus cost 5, zero "recommended" rows, 10 ranked rows with no 0-pip highlights, live kimi-k2.6 chat round-trip ("pong"), original default restored. Screenshots + menu dump in `results/2026-07-31-prod-001/`.

## Billing E2E — PASS (metering intact)

The dojo kimi-k2.6 turn settled correctly:

- `billable_events` 14:11:13Z moonshot/kimi-k2.6 (agent gamer)
- `rated_charges` 14:11:21Z `gw:161ef92fb8a9413d…` — **6 credits, settled**, vendor cost 44,595 µUSD, margin 10,000 µUSD, hold released via gwfin. No enforcement bypass.

### Tracked issue: usage/actions join-key mismatch (display bug, not a metering gap)

`finalize()` in `cloud/gateway/enforcement.py` writes `BillableEvent.call_id = ctx.call_id or ctx.operation_id` (tenant-supplied call id, e.g. `{agent_id}:8fd…`) but `RatedCharge.logical_call_id = ctx.operation_id` (`gw:…`). `/api/billing/usage/actions` joins `RatedCharge.logical_call_id == BillableEvent.call_id`, so whenever the tenant supplies a call id the charge is invisible in the actions statement. Scale: **6,932 of 6,956 events in the last 7 days do not join** — the actions view is missing essentially all charges. The linkage exists via `billable_events.source_idempotency_key = logical_call_id + ':1'`. Fix candidates: join on operation id (store it on the event), or normalize `call_id`. Not fixed in 063 — needs its own change + backfill decision.

## Incidents observed during verification

1. **Anthropic provider org out of API credits** — tenant `/proxy/anthropic/v1/messages` returning 400 "Your credit balance is too low to access the Anthropic API" (seen 14:11:25Z and 14:13:25Z on gamer; haiku condense calls failing, holds released at 0 credits). Fleet default primary is sonnet → fleet-wide anthropic outage until the org is topped up. **Needs immediate top-up.**
2. **Rayla (vaselin-test) gpt-realtime-2.1 mint burst** — 14×52-credit settled charges 14:07–14:15Z (~728 credits in ~8 min). Unexplained; worth checking the voice session loop.
3. Billing ops alerts active: `payments_granted_nothing`, `dead_jobs`, `holds_needs_reconciliation` (337 holds / 3,618 credits) — pre-existing, not caused by 063.

## Ops hygiene

- CP DB ipAllowList opened temporarily for verification, reverted to empty and verified closed.
- No secrets committed; Moonshot key lives only in Render/Fly env.
