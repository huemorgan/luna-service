# 07 — Metrics Cache Refresh

## Setup
- On `/dashboard/agents/{id}` for a real agent
- Note the "metrics cached at" timestamp visible somewhere in the page footer (or open devtools and read the API response from `/api/agents/{id}/details`)

## Steps
1. Note `metrics_cached_at` value (T0)
2. Wait 65 seconds
3. Reload the page
4. Re-read `metrics_cached_at` (T1)

## Expected
- T1 > T0 (the cache was refreshed because it was older than 60 s)
- Page renders in roughly the same time
- No errors

## Pass criteria
- T1 strictly later than T0
- Page still functional

## Fail criteria
- Cache never refreshes (T1 == T0)
- Cache refreshes on every reload, ignoring TTL (then it's not a cache)
