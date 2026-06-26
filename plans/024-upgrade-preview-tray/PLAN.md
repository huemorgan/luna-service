# 024 — Upgrade preview tray (new-version drawer under the machine)

> Replaces the bare "Upgrade" button (plan added in the machine list) with a
> connected drawer under each machine that shows **what's new** and **whether it's
> safe** before the user upgrades. Consumes Luna 0.17.002's pre-upgrade
> compatibility primitive (`luna/plans/008.7-upgrade-compat-check`) and the 008.6
> rehydrate/`load_status` truth.

## Goal (from the user)

When a newer image exists, don't show a one-click button. Instead:
1. A **collapsed one-line tray** attached under the machine box: "New version
   available — v0.17.002" + a **Details** expander.
2. Expanding opens a **full tray** under the machine box showing:
   - **What changed** — succinct release notes for the new version.
   - **Compatibility** — the score/verdict for the target version (from
     `upgrade-check`), per-plugin breakdown.
   - the **Upgrade** action(s).

## Dependencies

- Luna submodule **0.17.002+** pinned + images rebuilt (so tenants expose
  `POST /api/plugins/upgrade-check` and enforce `load_status`).
- Phase 022 `marketplace_upgrade` (`POST /api/p/plugin-marketplace/upgrade`) on
  the tenant — used by "update plugins & upgrade".
- Builds on the existing machine list (Dashboard `AgentCard`) and the
  `latest_version`/`upgrade_available` fields already on the agent payload.

## The 008.7 contract we consume (summary)

`POST /api/plugins/upgrade-check` on the tenant, body = target image contract
`{luna_version, sdk_major, sdk_min_major}`. Returns:
- `verdict`: `ok | upgrade_with_changes | blocked`
- `summary`: `{compatible, baked, needs_upgrade, unsupported, unknown}`
- `plugins[]`: `{name, installed_version, status, upgrade_to?, reason}` where
  `status ∈ compatible|baked|needs_upgrade|unsupported|unknown`.

Read-only, best-effort (unreachable source → `unknown`, never 500).

## Decisions

- **D1 — Cheap signal on list, full check on expand.** The "new version
  available" line comes from the existing version compare (no wake). The
  **compat-check runs only when the tray is expanded** — it wakes the machine and
  is too expensive to run for every row on page load. Result cached briefly
  (per agent+target) so re-expand is instant.
- **D2 — Compatibility "score" = verdict + a derived number.** Show the verdict
  badge (green `ok` / amber `upgrade_with_changes` / red `blocked`) and a derived
  score `compatible+baked / total` as "N of M plugins compatible". The badge is
  the real signal; the number is the at-a-glance.
- **D3 — Buttons follow the verdict** (008.7):
  - `ok` → **Upgrade**.
  - `upgrade_with_changes` → **Update plugins & upgrade** (primary; bumps each
    `needs_upgrade` via `marketplace_upgrade`, then `update_machine_image`) +
    **Upgrade anyway** (secondary).
  - `blocked` → **Upgrade anyway** (warns: `unsupported` plugins come back
    disabled-red) + emphasis on which plugins die. Always **Cancel**.
- **D4 — Notes are stored on the image, not computed live.** Captured at build
  time (see Phase A); the tray just renders them.
- **D5 — Old tenants degrade gracefully.** If the machine's current image
  predates 0.17.002 (`upgrade-check` 404/unavailable), show notes + a "couldn't
  verify compatibility (machine on an older image)" note and a plain Upgrade.

## Phase A — store the image contract + notes (backend, build time)

`LunaImage` gains (additive — in `image_config` JSONB or new columns):
- `luna_version` (already have `version`), `sdk_major`, `sdk_min_major` — read
  from the built image (`luna_sdk.__sdk_version__`, `__sdk_min_plugin_major__`)
  during the build step in `admin_routes.py`.
- `release_notes` (markdown) — captured at build from the luna git log between the
  previous main image's `git_sha` and this image's `git_sha` (commit subjects,
  trimmed to a succinct list). Admin-editable later via the image config UI.

Without `sdk_major`/`sdk_min_major` on the target image the control plane can't
form the `upgrade-check` request → tray falls back to D5.

## Phase B — control-plane endpoint

`GET /api/agents/{id}/upgrade-check` (account-scoped):
- target = current `is_main` built image's contract; if agent already on it →
  `{upgradable:false, reason:"already on latest"}`.
- wake the machine if asleep; `POST` its `/api/plugins/upgrade-check` with the
  target `{luna_version, sdk_major, sdk_min_major}`; cache the report (~60s).
- return `{upgradable:true, target_version, release_notes, verdict, summary,
  plugins:[…]}`. Tenant unreachable / pre-0.17 → `{upgradable:true,
  compat:"unavailable", release_notes, target_version}`.

`POST /api/agents/{id}/upgrade` (extend the existing one):
- add `mode: "upgrade_only" | "update_plugins_then_upgrade"` (default
  `upgrade_only`, current behavior).
- `update_plugins_then_upgrade`: for each `needs_upgrade` plugin call the tenant's
  `marketplace_upgrade`, then `update_machine_image`. Best-effort per plugin;
  report failures but still upgrade unless the user cancelled.

## Phase C — the tray UI (Dashboard `AgentCard`)

Replace the inline Upgrade button with a tray docked to the bottom of the machine
box (visually connected — shared border, no gap):

- **Collapsed:** `▲ New version available — v{target}` + `Details ⌄`. Amber
  accent (matches the existing "update available" pill).
- **On expand:** lazy `GET …/upgrade-check`, show a spinner, then the full tray:
  - **What's new** — `release_notes` rendered succinctly (heading + bullet list,
    capped; "show full notes" if long).
  - **Compatibility** — verdict badge + "N of M plugins compatible", then a
    compact per-plugin list colored by `status` (green compatible/baked, amber
    `needs_upgrade → vX`, red `unsupported`, grey `unknown` with reason).
  - **Actions** — buttons per D3, with a spinner + result toast; on success
    collapse the tray and refresh the agent (version + cleared upgrade flag).
  - **Fallback (D5):** notes + "compatibility unverified" note + plain Upgrade.

Reuse styling from `plans/017-machine-cards-tabs` (existing expand/tab patterns)
where it fits.

## Non-goals

- No runtime/canary compatibility proof (008.7 is declared-SDK only; label it).
- No auto-upgrade / scheduled upgrade.
- No changes to the 008.6 rehydrate or Luna's load-band enforcement (we only read
  `load_status` to show post-upgrade truth, separately).
- No new release-notes authoring workflow beyond capture-at-build + admin edit.

## Risks

- **Waking every machine** → only on expand, cached; never on list load (D1).
- **Pre-0.17 tenants** → D5 fallback, no hard failure.
- **"Update plugins & upgrade" partial failure** → per-plugin best-effort with a
  clear report; never silently skip the image upgrade decision.
- **Stale notes/contract** → captured at build; if missing, fall back to version
  compare + unverified compatibility.

## Acceptance

- A machine with a newer main image shows the collapsed "New version available"
  tray, not a bare button.
- Expanding shows succinct release notes + a verdict badge + per-plugin
  compatibility, fetched live (cached on re-expand).
- `upgrade_with_changes` offers "Update plugins & upgrade"; `blocked` warns and
  only offers "Upgrade anyway"; both always offer Cancel.
- Upgrading from the tray updates the machine and reflects the new version; no
  upgrade proceeds without the report having been shown.
- Pre-0.17 / unreachable tenant degrades to notes + plain upgrade, no error.

## Tests — tests/024-upgrade-preview-tray/

- Unit: `upgrade-check` proxy (target contract assembly, cache, pre-0.17
  fallback); `upgrade` `mode` branching (plugins-first vs anyway).
- Build-time contract capture (sdk numbers + notes persisted on `LunaImage`).
- Dojo: install a marketplace plugin → newer main image exists → expand tray →
  see notes + verdict → run each upgrade path → verify version + plugin states
  (incl. a `blocked` case showing red/`load_status` after "Upgrade anyway").
