# 024 — Upgrade preview tray · Execution report

Branch: `024-upgrade-preview-tray`

## What was built

**Phase A — image carries an upgrade contract** (`cloud/db/models.py`, `cloud/main.py`,
`cloud/api/admin_routes.py`)
- `LunaImage` gains `sdk_major`, `sdk_min_major`, `release_notes` (nullable;
  additive heal-columns in the lifespan).
- At build time the control plane reads `luna_sdk.__sdk_version__` /
  `__sdk_min_plugin_major__` from the build ref on GitHub and a succinct changelog
  (`compare prev_main_sha...ref`, falling back to recent commit subjects). All
  best-effort — a build never fails on a fetch error.
- Exposed on the admin image dict.

**Phase B — control-plane endpoints** (`cloud/api/agent_routes.py`)
- `_tenant_request()` — authenticated call into a tenant's Luna over the
  trusted-proxy channel (proxy secret + `x-luna-user` + `fly-force-instance-id`),
  auto-wakes + retries once, never raises.
- `GET /api/agents/{id}/upgrade-check` — resolves the main image as the target,
  short-circuits when nothing to do, else POSTs the tenant
  `/api/plugins/upgrade-check` with the target band and returns
  `{verdict, summary, plugins, release_notes}`. Degrades to `compat:"unavailable"`
  (still upgradable, notes shown) when the machine is asleep/unreachable/pre-0.17.
- `POST /api/agents/{id}/upgrade` extended with `mode`
  (`upgrade_only` | `update_plugins_then_upgrade`); the latter bumps `needs_upgrade`
  plugins via the tenant marketplace upgrade before the image swap.

**Phase C — the tray** (`cloud/ui/src/pages/Dashboard.tsx`)
- Removed the bare per-row "Upgrade" button. When `upgrade_available`, a collapsed
  tray is docked under the machine box: "New version available — v<target>" +
  Details. Expanding fetches the check and renders **What's new**, a colour-coded
  **Compatibility** verdict + per-plugin list, the SDK-only disclaimer, and
  verdict-driven actions. Up-to-date machines show no tray.

## E2E / dojo results (real browser against a local control plane)

Setup: local cloud server + control-plane Postgres, a `0.17.002` main image with an
SDK contract + notes, five seeded agents, and `fake_tenant.py` serving every verdict
path. Auth via a minted session cookie. (`seed.py`, `fake_tenant.py`.)

| Scenario | Result | Evidence |
|---|---|---|
| S1 collapsed tray replaces bare button; none when up-to-date | PASS | `024-s1-dashboard.png` |
| S2 expand compatible → notes + green "Compatible" + per-plugin + Upgrade | PASS | `024-s2-compatible-expanded.png` |
| S3 expand needs-upgrade → amber + "→ vX" + Update plugins & upgrade / Upgrade anyway | PASS | `024-s3-needs-updates.png` |
| S4 expand blocked → red "unsupported — will be disabled" + only Upgrade anyway + warning | PASS | `024-s4-blocked-buttons.png` |
| S5 unreachable tenant → notes + "couldn't reach…" + plain Upgrade (graceful) | PASS | `024-s5-fallback.png` |
| S6 Upgrade action wired → 503 "Fly API not configured" shown inline, no crash | PASS | `024-s6-upgrade-error.png` |

Backend paths were also verified directly via curl (ok / upgrade_with_changes /
blocked / unavailable).

## Known follow-up (Luna side)
- `update_plugins_then_upgrade` needs `marketplace_url` per plugin in the
  `/api/plugins/upgrade-check` response to drive the bumps; we forward it when
  present and record a skip otherwise. Worth asking Luna to include it.
- Real success path (actual image swap) needs Fly and is covered in production, not
  the local dojo.
