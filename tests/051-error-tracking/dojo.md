# 051 — Error tracking: production dojo

Date: 2026-07-21 · Service: Render srv-d8g5pd42m8qs73ekk2b0 (deploy
dep-d9fpae2ta46c73cnod6g, commits 9219eb1 + 760216a) · Test agent:
vaselin-t800 (28a921fb-85c7-4874-a56f-de917917f8ce, image 0.42.006,
plugin-feedback 0.2.0 installed from marketplaces.com.ai).

## What was verified live

| # | Feed | How | Result |
|---|------|-----|--------|
| 1 | Service self-tracking | Organic: proxy stream broke during a machine restart | `proxy_502` "Proxy stream broke (RemoteProtocolError)", source=service, severity=warning, agent resolved (fingerprint 7dc18deab078b80d…) |
| 2 | Reporter injection | `grep` of proxied t800 HTML | `<script src="/a/vaselin-t800/api/p/plugin-feedback/reporter.js" defer>` present in `</head>` |
| 3 | Reporter serving | GET reporter.js via proxy | 200, `application/javascript`, 7693 bytes, real reporter source (SPA fallback before 0.2.0 install) |
| 4 | Browser (ui) ingest | Synthetic batch POSTed to `/a/…/api/p/plugin-feedback/errors` with Shell bearer, exactly as reporter does | 202 `{"accepted":1}`; appears in `/api/admin/errors?source=ui` as `js_error`, message scrubbed path intact, agent_count=1 |
| 5 | Agent log handler | Organic: agent's own `plugin.prompt_sections_slow` warnings (plugin-mcp/curiosity/tasks) | Captured by `ErrorCaptureHandler`, flushed ≤30 s later, landed as source=agent `agent_report` warnings |
| 6 | `report_issue` tool | Real chat turn on t800: "use report_issue …" | Agent called it; event in admin API: kind=agent_report, severity=warning, context.client `{via: report_issue, plugin_version: 0.2.0, conversation_id: …}`, context.server `{slug, runtime_ref, image_version}` — server enrichment + attribution correct |
| 7 | Admin API filters | `?source=ui`, `?source=agent`, `?q=Dojo`, group detail by fingerprint | All correct; totals_by_severity accurate |

## Blocker found and fixed during dojo

`POST /api/admin/plugin-catalog/install` reported `plugin_installed:false`
repeatedly: the control plane's `_tenant_request` authenticates with
x-luna-user + x-luna-proxy-secret only, and agent-side auth
(`luna/auth/cookie.py: enforce_read_only_cookie` + `get_current_user`)
requires an agent-issued JWT bearer for **all writes** — GETs succeed, POSTs
401. Resolution used here: `POST /a/{slug}/api/auth/proxy-login` (agent
trusts the proxy-injected headers, returns a JWT), then POST
`/api/p/plugin-marketplace/install` with that bearer → 200, plugin
hot-loaded (sha256 verified against the published zip).

**Follow-up (not done):** the plugin-catalog install hook should perform this
proxy-login exchange itself; today any control-plane→agent POST silently
fails. Until then, fleet-wide plugin rollout happens at image releases.

## Polish items observed (not blocking)

- Log-handler messages include structlog's ANSI color codes and rendered
  timestamp (e.g. `\x1b[2m2026-07-21T16:09:26…`). Ugly in the admin UI and
  noisy for fingerprinting (digit-run normalization saves grouping, but the
  message should be clean). Fix in plugin 0.2.1: strip ANSI + use the bare
  event name in `_event_from_record`.
- `prompt_sections_slow` warnings fingerprint per-plugin (message contains
  the plugin name) — acceptable, arguably desirable.

Synthetic events left in place (2 groups, marked "Dojo 007"/"Dojo" in the
message) — harmless telemetry; retention pruning removes them after
`ERROR_RETENTION_DAYS` (60).
