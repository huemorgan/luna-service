# 007 — Image Management UI

## Goal

Complete the admin image lifecycle: build, inspect, promote, and roll out to all agents — all from the admin panel.

## Changes

### 1. "Migrate All" button on Images page

The backend already exists (`POST /api/admin/machines/migrate-all`). Add a button to the UI that:
- Appears next to the main image when agents are on an older version
- Shows progress (X of Y updated)
- Reports errors inline

### 2. Per-agent image version on Dashboard

Show which image version each agent is running in the agent list. Highlight agents that are behind the main image.

### 3. Version bump sync

Update `cloud/.luna-version` to `0.01.002` to match the luna submodule bump from plan 005.919.

## Files

| File | Change |
|---|---|
| `cloud/.luna-version` | `0.01.001` → `0.01.002` |
| `cloud/ui/src/pages/admin/ImagesPage.tsx` | Add Migrate All button + count of outdated agents |
| `cloud/ui/src/pages/Dashboard.tsx` | Show image version per agent, highlight outdated |

## Risks

- `migrate-all` restarts machines sequentially. If one fails, the rest still proceed. Errors are returned in the response and shown in the UI.
