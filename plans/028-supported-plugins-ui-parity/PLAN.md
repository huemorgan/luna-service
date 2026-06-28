# Plan 028 — Supported plugins: exact UI/UX parity with the Default set

## Problem

The Supported plugins card was built wrong. It renders a flat row per plugin with an
**"Install on…" dropdown that lists every machine/agent** plus an install button. That's
not the intent. Admin should never pick a machine here.

Intent: the Supported list is just a **catalog of non-bundled plugins, each with a default
key binding**. It should look and behave **exactly like the Default plugin set** (the
expandable cards with the default-key control), with **one difference: the plugin is not
baked into the image**. When a user later installs that plugin, the bound key is hooked
automatically — no per-agent admin action.

Concrete user story: a non-bundled `plugin-image-generation`. Admin picks it in the
Supported list, binds the Gemini key from the key list. Done. When a user installs the
plugin, it comes up with that key provisioned by default.

## Confirmed scope decisions

- **One key per plugin.** A catalog entry binds exactly one `service_slug`. No multi-vendor
  / multiple-key bindings (e.g. an image plugin using Gemini + OpenAI at once) — explicitly
  out of scope for now.
- **No per-agent install UI.** Remove the "Install on…" machine dropdown + install button
  entirely. The admin only defines the binding.

## Goal

Make the Supported plugins card use the **same expandable plugin-card UI** as the Default
plugin set (`PluginSetEditor`), with the only differences being:
- it's added to the **supported catalog**, not the baked `plugin_set`;
- copy says it's **not bundled — provisioned when the user installs it**;
- no version/upgrade pinning UI (nothing is baked), and no "Install on…" control.

Everything else — the marketplace picker to add, the default-key control (service picker +
proxy/env + keyed/no-key badge), remove — is identical to the Default set.

## Changes (frontend only)

### C1. Extract the shared expandable card
Pull `PluginCard` out of `PluginSetEditor` into a shared component (e.g.
`PluginCard.tsx`) that takes: a name, an optional version/latest (for the baked set),
the `keying` (services + catalog binding + onBind/onMode), and feature flags:
- `showVersion` (baked set: true; supported: false)
- `showInstall`: removed everywhere — delete the per-agent `InstallControl` usage.
`PluginSetEditor` consumes it with `showVersion`; behavior unchanged for List A.

### C2. Rewrite `SupportedPluginsEditor` to render the same cards
- Keep the `MarketplacePicker` (add from marketplace, `allowNonBakeable`).
- Render each supported entry as the **same expandable `PluginCard`** as the Default set,
  scoped to its own service (`allowedSlugs` = the plugin's `key_service` / current binding),
  showing the default-key control + keyed/no-key badge.
- Collapsed line shows the plugin name + a small **"not bundled"** tag instead of a baked
  version; expanded shows the **Default key** row (identical control) + **Remove**.
- **Delete** the `InstallControl` (the machine list) from this card and from `pluginKeys.tsx`.
- `DefaultsPage` no longer needs to pass `agents` to the Supported editor.

### C3. Copy
Card already updated to: "…then when the user installs it, it'll have a provisioned key by
default." Keep. Add a per-row hint only if needed ("not bundled — installed on demand").

## Backend
None. The binding (`PluginCatalogEntry` tier=supported + `service_slug`) already drives
membership provisioning in `build_gateway_env` when the plugin is part of an agent's
effective plugins. The admin-initiated `/plugin-catalog/install` endpoint can stay in the
API (harmless) but is no longer surfaced in the UI.

Note (follow-up, not this plan): auto-provisioning on a **user-initiated** install requires
the agent to report its installed plugins so the control plane adds the bound key (026 §Install
hook option 2). That's the mechanism behind "hooked by default when installed"; if it's not
yet wired, it's a separate task — this plan only fixes the admin UI to match the Default set.

## Out of scope
- Multiple keys / multi-vendor per plugin.
- Per-agent install action.
- User-initiated install auto-provision wiring (follow-up).

## Test plan
- `cd cloud/ui && npm run build` green.
- Browser walkthrough on Defaults: the Supported card shows the **same expandable cards** as
  the Default set, with a default-key picker + proxy/env + keyed badge, a "not bundled" tag,
  and **no machine list anywhere**. Add `plugin-image-generation` (or `plugin-monday`), bind
  a key from the list, confirm the row matches the Default-set card visually and functionally.

## Acceptance
- Supported plugins card is visually/functionally identical to the Default plugin set except
  it's non-bundled.
- No "Install on…" / machine dropdown anywhere in the Supported card.
- One key per plugin, bound from the key list.
