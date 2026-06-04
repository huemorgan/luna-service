# Phase 006 — Agent Detail Page · Test Scenarios

Dojo-style scenarios. The LLM agent opens a browser, runs the steps, takes screenshots, reads DOM, and judges pass/fail. No coded assertions.

Pre-conditions for all scenarios:
- Control plane running (`make dev` in `cloud/`) or production reachable
- Logged in via Google (or stub identity in dev)
- At least one agent exists in the account (or create one inside the scenario)

## Scenarios

- `01-open-detail-from-dashboard.md` — click an agent → land on detail page within 1 s
- `02-identity-and-routing-rendered.md` — slug, URL, account, creator are all populated from real data
- `03-compute-card-shows-fly-data.md` — machine ID / region / image / size match the agent's actual Fly machine
- `04-storage-card-postgres-and-r2.md` — postgres schema = `luna_user_<slug>`, R2 prefix displayed
- `05-size-presets-current-selected.md` — size dropdown shows Fly presets, current size is pre-selected, dropdown is disabled with "Coming soon"
- `06-coming-soon-cards-rendered.md` — Activity + Spend cards render as labeled placeholders, not blank
- `07-cache-refresh.md` — `metrics_cached_at` advances after 60 s
- `08-back-to-dashboard.md` — breadcrumb / back link returns to `/dashboard`
- `09-stale-machine-graceful.md` — if Fly returns 404 for the machine, page still renders with compute card showing "machine not found" instead of crashing
