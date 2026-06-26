# 024 — Upgrade preview tray · E2E scenarios

Browser dojo against a local cloud control plane. Setup (see `seed.py` +
`fake_tenant.py`): an admin user, an account, a **main built image** carrying an
SDK contract + release notes, and agents whose `image_version` lags it. A fake
tenant serves `POST /api/plugins/upgrade-check` so the verdict paths render.

Auth: mint a `luna_session` cookie (session_secret = `dev-session-secret-change-me`).

---

## S1 — Collapsed tray replaces the bare button
- Open `/dashboard`.
- An agent with a newer main image shows a **collapsed tray docked under the
  machine box**: text "New version available — v<target>" + a **Details**
  expander. NOT a standalone "Upgrade" button on the machine line.
- An agent already on the latest version shows **no tray**.
- PASS: tray present only when an upgrade exists; visually connected to the card
  (shared border / no gap).

## S2 — Expand: compatible (verdict ok)
- Click **Details** on a machine whose plugins are all compatible.
- Tray expands to a full drawer under the box showing:
  1. **What's new** — succinct release notes for v<target>.
  2. **Compatibility** — green badge "Compatible", "N of N plugins compatible",
     a per-plugin list all green.
  3. An **Upgrade** button.
- PASS: notes + green verdict + Upgrade visible; data fetched on expand.

## S3 — Expand: needs upgrade (verdict upgrade_with_changes)
- Expand a machine with at least one `needs_upgrade` plugin.
- Compatibility shows an **amber** verdict; the plugin row reads
  "update available → vX".
- Buttons: **Update plugins & upgrade** (primary) + **Upgrade anyway** + Cancel.
- PASS: amber verdict, per-plugin amber line, both upgrade buttons present.

## S4 — Expand: blocked (verdict blocked)
- Expand a machine with an `unsupported` plugin.
- Compatibility shows a **red** verdict; the plugin row is red "unsupported".
- Buttons: **Upgrade anyway** (with a warning that the plugin lands disabled) +
  Cancel. No plain one-click "Upgrade".
- PASS: red verdict, warning copy, only "Upgrade anyway" + Cancel.

## S5 — Fallback: tenant unreachable / pre-0.17
- Point a machine's tenant at a dead/old endpoint, expand.
- Tray shows release notes + a "couldn't verify compatibility (machine on an
  older image)" note + a plain **Upgrade** button. No crash, no spinner stuck.
- PASS: graceful fallback, upgrade still offered.

## S6 — Upgrade action result
- From S2's tray, click **Upgrade** (fake tenant + no FLY token → backend returns
  503 "Fly API not configured"); the UI surfaces the error inline, tray stays
  open, nothing crashes.
- PASS: action wired to `POST /api/agents/{id}/upgrade`, error shown cleanly.
  (Real success path is covered by the unit tests + production; local has no Fly.)
