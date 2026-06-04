# 03 — Compute Card Shows Real Fly Data

## Setup
- Agent in `running` state with a real Fly machine
- On `/dashboard/agents/{id}`

## Steps
1. Read the "Compute" card
2. Run `fly machines list --app luna-tenants-prod --json` from terminal (or check via Fly dashboard)
3. Find the matching machine by ID
4. Compare card values to Fly response

## Expected
The card shows:
- **Machine ID**: matches `agent.runtime_ref` and Fly's machine `id`
- **App**: `luna-tenants-prod`
- **Region**: e.g. `sjc (San Jose)` — region code + friendly name
- **Image**: matches `config.image`
- **Size**: rendered via a dropdown `<select>` (see scenario 05); shows current `cpu_kind · cpus · memory_mb`
- **State**: matches Fly's state (`started`, `stopped`, etc.)
- **Last started**: human-friendly relative time

## Pass criteria
- Machine ID matches exactly
- Region/size/state all reflect Fly's truth
- No "—" or "unknown" values for an active agent

## Fail criteria
- Field values don't match Fly
- Card empty for a running agent
- Errors fetching from Fly are surfaced as a banner, not a blank card
