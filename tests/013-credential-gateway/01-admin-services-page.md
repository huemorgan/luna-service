# 01 — Admin services page shows the registry

## Preconditions
- Control plane running locally, admin logged in
- Fresh DB (or at least: seeds ran on startup)

## Scenario
1. Navigate to `http://localhost:8100/admin/services`
2. Screenshot the page

## Expected behavior
- A "Services" item appears in the admin sidebar
- The page lists the seeded services: `anthropic`, `openai`, `tavily`,
  `composio` — each showing display name, upstream URL, auth style,
  enabled state, and provision-by-default state
- `anthropic` and `openai` are enabled + provisioned by default;
  `composio` is disabled (Luna-side support pending 007.001)
- Each service row shows its key count (0 on a fresh DB)
- An "Add service" button exists; clicking it opens a form with slug,
  display name, upstream URL, auth style fields
- Adding a service `echo-test` with upstream `http://localhost:9009`
  and auth style `header:x-api-key` makes it appear in the list
  immediately — **no code change, no restart** (this is the "dynamic
  services" requirement)

## Fail conditions
- Services page 404s or missing from sidebar
- Seeded rows missing or wrong
- Adding a service requires a restart to appear
- Any key value visible anywhere on this page
