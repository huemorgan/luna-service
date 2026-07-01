# 025 — Fleet upgrade: new Luna core + storage plugins + marketplace backfill

> Roll the **new Luna** (submodule `93fe7bb`: 008.8 upgrade-awareness, 008.9
> interruptible chat, **008.95 Phase A** `ctx.storage`) onto **every** tenant
> machine, ship the **001 files-mapping** plugin bumps (`plugin-files 0.3.0`,
> `plugin-browser 0.3.0`) in the baked image, and **backfill** the plugins that
> used to be hardcoded in Luna core and are now marketplace-only — so no instance
> silently loses capability across the swap.
>
> Companion docs (read for the contract details, do **not** re-derive them here):
> - `../luna-plugins/plans/001-migrate-files-mapping/PLAN.md` + `luna-service-recommendation.md` (the plugin half + the hosted rollout shape)
> - `luna/plans/008.95-chat-attachments/{STORAGE-GOVERNANCE,PLUGINS-SUGGESTION,LUNA-SERVICE-SUGGESTION}.md` (storage contract + durability)
> - `luna/plans/008.6-luna-service-upgrade-fix/LUNA-SERVICE-SUMMARY.md` (artifact store + rehydrate)
> - `luna/plans/008.8-agent-upgrade-awareness/LUNA-SERVICE-SUMMARY.md` (post-upgrade health report)

## What we're actually shipping

Three things, in this order, because each depends on the previous:

1. **A new main image** — the bumped Luna submodule + a bumped baked plugin-set.
2. **A fleet roll** of that image onto every machine (`migrate-all`).
3. **A per-tenant marketplace backfill** of formerly-in-tree plugins that the new
   core no longer ships and that aren't in the baked set.

The headline mechanics already exist (`update_machine_image`,
`POST /api/admin/machines/migrate-all`, 008.6 rehydrate, 008.8 awareness). The
**new** work in this plan is mostly (a) the plugin-set bump + sha re-pin, and (b)
the backfill job — driving per-tenant marketplace installs from the control plane.

## The three plugin populations (this is the whole problem)

After the swap, every plugin an agent runs comes from exactly one of:

| Population | Source | Survives the swap because… | Examples |
|---|---|---|---|
| **Core in-tree** | shipped inside `luna/` | rebuilt into every image | vault, memory, identity, meta, approvals, webui, marketplace, **upgrade-awareness** |
| **Baked set** | `LUNA_PLUGIN_SET_DIR=/opt/luna/plugin-set` (from `plugin-set.toml` / image `plugin_set`) | re-baked into every image | charts, web-access, **files**, **browser** |
| **Marketplace-installed** | `PluginRow source="marketplace"` + `plugin_artifacts` in the tenant DB | **008.6 rehydrate** restores from DB/marketplace at boot | anything a tenant installed |

The danger case the user is calling out: a plugin that was once **core in-tree**,
got **decoupled to the marketplace** (charts, web-access, files, mcp, recall,
funnelfighters, monday, render, cloudflare, …), and on a given instance is
**neither baked nor a marketplace `PluginRow`**. Old in-tree plugins had no
`PluginRow` and no `plugin_artifacts` — so 008.6 rehydrate **will not** restore
them, and they're not in the image. On the new core they simply **disappear**.
Backfill (Phase 4) is exactly for this set.

## Decisions

- **D0 — One image carries everything.** New Luna submodule **and** the 001
  plugin bumps go in the **same** main image. Don't stage them separately: the
  001 plugins only matter end-to-end once the core ships `ctx.storage`, which is
  in this same submodule. Verified present: `luna/luna/plugins/context.py::storage`,
  `luna_sdk` re-exports `StorageProvider`/`StoredFile`.

- **D1 — Baked vs backfilled, split by bakeability.** The curated **leaf** set
  (`plugin-files`, `plugin-browser`, `plugin-web-access`, `plugin-charts`) goes
  in the **baked image** — deterministic, fleet-wide, and the way every agent
  gets `ctx.storage`. Connectors and dep-carrying plugins (`plugin-monday`,
  `plugin-render`, `plugin-cloudflare`, and anything PyPI-heavy) are **not
  bakeable** (Luna 008.5 §5 dependency isolation; `admin_routes.NON_BAKEABLE_PLUGINS`)
  → those are restored **per-tenant** via marketplace install (Phase 4).

- **D2 — `plugin-files` is the *only* `"storage"` registrant.** The provider
  registry raises on a duplicate `"storage"` key and that aborts boot. Bake
  exactly one storage provider (`plugin-files 0.3.0`). Do **not** also bake a
  second storage plugin. (When durable storage lands — D6 — it must `replace`,
  not double-`register`.)

- **D3 — Backfill list comes from the post-upgrade health report, not guesswork.**
  After an instance boots the new image, 008.8's `plugin-upgrade-awareness` writes
  `upgrade_awareness_reports` (tenant DB) listing every plugin and its status
  (`not_loaded | needs_reinstall | failed | …`). The backfill job reads that row
  per tenant and installs each entry that is (a) absent and (b) available in the
  official marketplace and (c) not in the baked set. This makes the backfill
  **evidence-driven and idempotent** instead of "install everything everywhere."
  (Fallback when a report is missing: enumerate enabled `PluginRow`s whose code
  didn't load — same signal, lower fidelity.)

- **D4 — Backfill installs are control-plane-driven over the existing proxy auth.**
  Reuse the proxy identity shape (`cloud/api/proxy.py::_proxy_request`): POST to
  `{internal_url}/api/p/plugin-marketplace/install` with
  `x-luna-proxy-secret = derive_proxy_secret(root, agent_id)`,
  `x-luna-user = <owner email>`, `fly-force-instance-id = runtime_ref`, after a
  wake (`_try_wake_agent`). Body: `{marketplace_url, name, version}` against the
  official marketplace. The install endpoint already persists the artifact
  (008.6), so it self-heals on all future upgrades. **No agent conversation
  required** — 008.8's in-chat remediation is the *manual* path; this is the
  *fleet* path.

- **D5 — Staggered, evidence-gated rollout.** Canary (a test agent on the new
  image) → small cohort → fleet. `update_machine_image` preserves machine id and
  the tenant Postgres, so this is non-destructive and reversible (re-point to the
  previous main image).

- **D6 — Durable storage is a *follow-up* (026), explicitly out of scope here.**
  Baked `plugin-files 0.3.0` writes to the **ephemeral** container disk
  (`~/.luna/files`), wiped on every deploy (008.6's whole premise). So screenshots
  will be *governed and visible in Files within a session* but **not durable
  across a deploy**. That's an acceptable, strictly-better-than-today behavioral
  step (001 is "behavior + contract"; durability is "002"/the
  `LUNA-SERVICE-SUGGESTION` DB-blob provider). Shipping a durable `"storage"`
  provider + read-only-rootfs containment is its own phase — see "Follow-up".

## Phase 0 — publish the 001 plugins to the marketplace (prereq)

The baked-set build fetches artifacts from the **official marketplace** and
sha256-verifies them — so the new versions must exist there first.

1. In `../luna-plugins`: package + publish `plugin-files 0.3.0` and
   `plugin-browser 0.3.0` (`scripts/package_plugin.py` → `scripts/publish_plugin.sh`
   → lands in `../luna-marketplaces` official index). Run
   `scripts/check_no_raw_fs.py plugins/` first (001 Phase C guardrail).
2. Confirm both appear at `https://luna-marketplaces.onrender.com/mp/official/index.json`
   with a `sha256`, and the artifact downloads at
   `…/plugins/<name>/<version>/artifact.zip`.
3. Record both `sha256` values for Phase 1.

> Note: `plugin-browser` source currently lives in `luna-plugins/`; verify it has
> a `marketplace-src` entry in `luna-marketplaces` (publish path) — `plugin-files`
> already does. If browser isn't wired into the marketplace yet, that wiring is
> part of this phase.

## Phase 1 — build the new main image

1. **Submodule pointer:** confirm `luna/` is at `93fe7bb` (done — pulled this
   session) and that `cloud/.luna-version` / the build will pick it up.
2. **Plugin-set bump (two places, keep in sync):**
   - Seed: `plugin-set.toml` → `plugin-files = 0.3.0`, add `plugin-browser = 0.3.0`,
     keep `plugin-web-access 0.2.0` + `plugin-charts 0.1.0`; re-pin every `sha256`
     from the live index (the bake step fails closed on mismatch).
   - Image selection: the admin **Plugin Set** picker (`image_config.plugin_set`,
     `PUT /api/admin/images/{id}/config`) is the real source of truth and overrides
     the seed. Set the same four there with fresh sha256 from
     `GET /api/admin/marketplace/catalog`.
3. **Build:** `POST /api/admin/images/build` (branch `main`) → GitHub Actions
   `build-luna-image.yml` bakes the set (`scripts/bake_plugin_set.py`) and pushes
   `registry.fly.io/luna-agents:{version}`. Wait for `build-complete` webhook →
   `built`.
4. **Verify the baked image** before promoting: exactly one `"storage"` provider;
   `plugin-set.lock.json` lists files 0.3.0 + browser 0.3.0; image boots.

## Phase 2 — canary

1. `POST /api/admin/images/{id}/test-agent` → a fresh agent on the new image.
2. Dojo (real browser, per `skills/run-dojo`): have the agent screenshot a page →
   confirm the result is a **Files → `browser/…`** ref + URL (not `/tmp`, not a
   bare data URL), it opens in the Files UI, and `file_list path=/browser` shows
   it. Confirm 008.9 streaming + two-stage Stop work and 008.8 posts an upgrade
   notice on first message.
3. Promote: `POST /api/admin/images/{id}/set-main` (also warms the Fly cache).

## Phase 3 — backfill tooling (the new code in this plan)

`cloud/migration/plugin_backfill.py` (+ admin routes):

- `derive_backfill(agent)` → read the tenant DB's latest `upgrade_awareness_reports`
  row (D3); return plugins with status in `{not_loaded, needs_reinstall, failed}`
  that exist in the official marketplace catalog and are **not** in the agent's
  baked set. (Fallback: enabled `PluginRow`s whose code is absent.)
- `install_one(agent, name, version)` → the D4 proxy POST to
  `/api/p/plugin-marketplace/install`, with wake + retry/backoff (reuse the relay
  forwarder's posture; don't hand-roll a new delivery loop).
- Admin endpoints (mirror `migrate-all`):
  - `POST /api/admin/machines/{id}/backfill-plugins` (one agent; `dry_run` flag
    returns the computed list without installing).
  - `POST /api/admin/plugins/backfill-all` (fleet; staggered; returns per-agent
    `{installed, skipped, errors}` and writes an `AuditLog`).
- **Idempotent:** a plugin already loaded/installed is skipped; a partial run is
  safe to re-run.

## Phase 4 — fleet roll + backfill

1. **Cohort the fleet:** start with a handful, watch `/api/health` + the 008.8
   `overall` field (`upgrade_awareness_reports`) on each.
2. **Image roll:** `POST /api/admin/machines/migrate-all` (or per-machine
   `update-image`) — `update_machine_image`, machine id + tenant DB preserved.
3. **Let 008.6 + 008.8 run:** on first boot each machine rehydrates its
   marketplace `PluginRow`s and writes its upgrade report.
4. **Backfill:** run `backfill-all` (start with `dry_run` to eyeball the computed
   per-tenant lists), then execute. This is what restores the formerly-in-tree
   plugins that have no `PluginRow` to rehydrate.
5. **Repeat per cohort** until the fleet is on the new main and every agent's
   report is `healthy` (or the only `action_needed` items are credentials, which
   are owner-driven, not ours).

## Phase 5 — verify

- Every machine on the new main version (`GET /api/admin/machines` `image_version`).
- No agent reports a baked/backfilled plugin as `not_loaded`/`needs_reinstall`.
- A screenshot on a real agent lands at `browser/…` and opens (within-session).
- Backfilled plugins now have a `plugin_artifacts` row (self-healing confirmed).

## Follow-up (out of scope — next phase, 026): durable storage + containment

Baked `plugin-files` on cattle machines means files don't survive a deploy. The
`LUNA-SERVICE-SUGGESTION.md` answer: register a **durable `"storage"` provider**
(DB-blob first, mirroring 008.6's plugin-artifact reasoning; R2 later) that
**`replace`s** plugin-files' disk impl at boot, plus a read-only rootfs +
tmpfs-scratch containment. That's a deploy/infra change with its own
single-registrant + backfill migration — keep it separate so this fleet upgrade
stays low-risk and reversible.

## Risks

- **sha256 drift** — re-pin `plugin-set.toml` *and* `image_config.plugin_set`
  from the live index; the build fails closed otherwise. Easy to forget the
  picker copy.
- **Double `"storage"` registrant** → boot crash fleet-wide. Bake exactly one
  (D2); the durable provider (026) must `replace`, not `register`.
- **Backfill spoof / wrong tenant** — installs are scoped by the per-agent
  derived proxy secret + the owner identity header; one agent can only touch its
  own machine. Never broadcast a single owner identity across machines.
- **Marketplace down during backfill** — install endpoint fails 4xx/5xx; the job
  retries/back-offs and records per-agent errors (no partial-state corruption;
  re-runnable).
- **A formerly-in-tree plugin isn't published to the marketplace** → backfill
  can't restore it. Catch this in the Phase 4 `dry_run` (it'll show as
  "not in catalog"); publish it (Phase 0 path) before completing the fleet.
- **Non-durable files surprise users** — set expectations (within-session only)
  until 026; don't advertise persistence yet.
- **008.9 single-replica assumption** — fine (one process per tenant); don't run
  >1 replica per agent.

## Acceptance criteria

- [ ] `plugin-files 0.3.0` + `plugin-browser 0.3.0` published to the official
      marketplace; `check_no_raw_fs` green.
- [ ] New main image built from submodule `93fe7bb` with both 0.3.0 plugins +
      web-access + charts baked (sha256 verified); exactly one `"storage"`
      provider.
- [ ] Canary passes the dojo screenshot-to-`/browser` walkthrough; 008.9/008.8
      behaviors visible.
- [ ] Fleet rolled via `migrate-all` (canary → cohort → all); machine ids + tenant
      DBs preserved.
- [ ] Backfill job restores every formerly-in-tree plugin a tenant relied on,
      idempotently, scoped per-agent, with audit + per-agent result; `dry_run`
      previews the computed list.
- [ ] Post-roll: no agent reports a baked/backfilled plugin as broken; backfilled
      plugins gain `plugin_artifacts` rows.

## Open questions (need answers before/with execution)

1. **Per-instance plugin truth:** OK to rely on the 008.8 `upgrade_awareness_reports`
   as the backfill source (D3), or do you have an explicit per-instance "these
   plugins" list you'd rather drive from? (Reports are the lower-effort, evidence-
   based default.)
2. **Fleet size / blast radius:** how many live tenant machines, and any that must
   be hand-held (high-value users) vs. safe to batch?
3. **Durability now or 026:** confirm we ship 001 behavioral now and defer the
   durable `"storage"` provider + containment to a follow-up (recommended), vs.
   folding DB-blob storage into this roll.
4. **Browser in the marketplace:** is `plugin-browser` already publishable to
   `luna-marketplaces` (it's in `luna-plugins` but I didn't confirm a
   `marketplace-src` entry), or does Phase 0 include wiring it up?
