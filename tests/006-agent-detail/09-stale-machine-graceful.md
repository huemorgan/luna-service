# 09 — Stale Machine — Graceful Degrade

## Setup
- An agent whose `runtime_ref` points to a machine that no longer exists on Fly (simulate by deleting the machine on Fly directly without going through the control plane, or pick an agent in `error` state with a stale runtime_ref)

## Steps
1. Navigate to `/dashboard/agents/{id}` for that agent
2. Observe the Compute card

## Expected
- Page still renders
- Compute card shows "Machine not found on Fly" or similar message
- Identity/Storage/Coming-Soon cards still render normally
- No JS console errors

## Pass criteria
- Page does not crash
- Compute card surfaces the error rather than going blank

## Fail criteria
- Whole page blank or shows 500
- React error overlay
