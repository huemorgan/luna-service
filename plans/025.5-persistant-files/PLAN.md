# 025.5 — Persistent files: per-agent Fly Volume for `plugin-files`

> Make the filesystem plugin as durable as the per-agent Postgres: every agent
> gets a **Fly Volume** mounted at `/workspace`, and `plugin-files` runs in `fly`
> backend mode against it. Files survive restarts, deploys, and image rolls — the
> same way the tenant DB already does.
>
> Companion docs (the plugin half — do **not** re-derive here):
> - `../luna-plugins/plans/002-plugin-files-persistence/PLAN.md` (one plugin, four backends; `fly` mode)
> - `../luna-plugins/plans/002-plugin-files-persistence/luna-service-suggestion.md` (the hosted integration this plan implements)
>
> Builds on **025** (new core + `plugin-files` baked). 025 shipped `plugin-files`
> on the **ephemeral** container disk (`~/.luna/files`, wiped every deploy — 025
> D6). This plan makes it durable. It is the "026 follow-up" 025 punted, brought
> forward.

## Is it doable? (yes)

A Fly Volume is a slice of NVMe attached to one machine, encrypted at rest, in the
machine's region, with daily snapshots. Verified against our own runtime:

- `update_machine_image` and `update_machine_env` (`cloud/runtime/fly_machines.py`)
  both `GET` the full machine config and `POST` it back unchanged except for the
  field they touch — so once `config.mounts` exists, **fleet rolls keep the volume
  and its data**. Same mechanism that already preserves the tenant DB env.
- `restart.policy=always` + `auto_destroy=false` are already set → the machine
  (and its volume) persists across crashes/restarts.

**The one honest caveat:** a single volume is **host-pinned, not HA**. It survives
deploys/restarts/image swaps, but if the physical host's drive fails the volume is
gone unless restored from a snapshot. There is no EBS-style detach/reattach. So
"persistent" ✅ ≠ "highly available." Mitigation = Fly daily snapshots (bump
retention) and/or periodic sync of the working set to R2 (`object` backend). This
matches the durability profile we already accept for a one-machine-per-agent model.

## Scope

- **In:** per-agent Fly Volume provisioning + mount + env; `volume_id` on the agent
  record; reuse-on-recreate; delete-on-destroy; backfill existing machines;
  de-hardcode the storage card; bake/roll `plugin-files` in `fly` mode; containment
  (read-only rootfs + tmpfs scratch).
- **Out:** the plugin code itself (lives in `luna-plugins` plan 002 — this plan
  consumes `plugin-files 0.4.0`); the `object`/`db` backends as the *primary* store
  (offered as backup/fallback, not the hot path); cross-host HA.

## Dependencies

- **`plugin-files 0.4.0`** (luna-plugins 002) published to the official marketplace
  and bakeable — it reads `LUNA_FILES_BACKEND=fly` / `LUNA_FILES_ROOT` /
  `LUNA_FILES_DURABLE` and reports `file_storage_status`. **Blocker:** if 002 isn't
  published yet, do that first (its Phase 0, same path 025 Phase 0 used).
- 025 landed (new core with `ctx.storage`, `plugin-files` baked). This plan bumps
  the baked version 0.3.0 → 0.4.0.
- `FLY_API_TOKEN` / `FLY_APP` already wired in `_get_client()`.

## Decisions

- **D1 — `fly` is the hosted default backend.** Fast local NVMe, real POSIX
  (dirs + in-place edits → works as a code workspace), durable across image swaps.
  `object` (R2) and `db` are backup/fallback, not the hot path.
- **D2 — One volume per agent, mounted at `/workspace`.** `LUNA_FILES_ROOT=/workspace/files`.
  Name `luna_data_{slug}` (Fly vol names are `[a-z0-9_]` → replace `-` with `_`).
  Volume region **must** equal the machine region (`region` already computed in
  `provision()`).
- **D3 — Durability is declared, never guessed.** Set `LUNA_FILES_DURABLE=1` so the
  plugin reports `durable=true` honestly; it never sniffs the filesystem.
- **D4 — Idempotent reuse by name.** `provision()` looks up the volume by
  `(name, region)` and reuses it; only creates if absent. The recreate branch
  (destroy-stale-then-recreate) **re-attaches the same volume** — never orphans data.
- **D5 — Lifecycle owns the volume's whole life.** Create on first provision; keep
  across image/env rolls (free, Fly preserves it); reuse on recreate; **delete on
  agent delete** so we don't pay for orphan volumes.
- **D6 — Snapshots are the backup story (HA caveat).** Create volumes with
  `encrypted=true` and a snapshot retention (e.g. 7d). Document optional R2 sync as
  a later enhancement; do not block on HA.
- **D7 — Containment is defense-in-depth, shipped here.** Read-only container root
  except `/workspace`; `TMPDIR`/`LUNA_SCRATCH_DIR` → ephemeral tmpfs. A
  non-compliant plugin then physically cannot scatter durable files outside the
  mount.

## Phase 0 — prerequisite: `plugin-files 0.4.0` published & baked

1. In `../luna-plugins`: ensure plan 002 `plugin-files 0.4.0` (fly/object/db
   backends + `file_storage_status`) is packaged + published to the official
   marketplace with a `sha256` (same path as 025 Phase 0). Run
   `scripts/check_no_raw_fs.py plugins/` first.
2. Bump the baked set: `plugin-set.toml` → `plugin-files = 0.4.0`, re-pin `sha256`;
   also update the admin **Plugin Set** picker (`image_config.plugin_set`) to 0.4.0
   with fresh sha256 (the picker overrides the seed; build fails closed on drift).
3. Build the new main image (`POST /api/admin/images/build`, branch `main`) → wait
   for `built`. Verify exactly one `"storage"` registrant and `plugin-files 0.4.0`
   in `plugin-set.lock.json`.

## Phase 1 — volume provisioning in the runtime

`cloud/runtime/fly_machines.py`:

1. **`provision()` — ensure the volume before `POST /machines`:**
   ```python
   vol_name = f"luna_data_{spec.agent_slug}".replace("-", "_")
   size_gb = machine_cfg.get("volume_gb", 1)
   vols = (await client.get("/volumes")).json()
   vol = next((v for v in vols if v["name"] == vol_name and v["region"] == region), None)
   if vol is None:
       r = await client.post("/volumes", json={
           "name": vol_name, "region": region, "size_gb": size_gb,
           "encrypted": True, "snapshot_retention": 7,
       })
       r.raise_for_status(); vol = r.json()
   volume_id = vol["id"]
   ```
   (Compute this **after** `region` is resolved, **before** the machine payload.)
2. **Add the mount + env to `payload["config"]`:**
   ```python
   "mounts": [{"volume": volume_id, "path": "/workspace"}],
   ```
   and into `env_vars`:
   ```python
   "LUNA_FILES_BACKEND": "fly",
   "LUNA_FILES_ROOT": "/workspace/files",
   "LUNA_FILES_DURABLE": "1",
   "LUNA_SCRATCH_DIR": "/tmp/luna-scratch",
   "TMPDIR": "/tmp/luna-scratch",
   ```
3. **Recreate branch (D4):** the existing "destroy stale machine before recreate"
   path must NOT drop the volume — because we reuse by name in step 1, the recreate
   simply finds and re-mounts the same `volume_id`. Add a comment + a test asserting
   no second volume is created.
4. **`destroy()` (D5):** after `DELETE /machines/{ref}`, look up the agent's
   `volume_id` (passed via `RuntimeHandle.extra` or re-derived by name) and
   `DELETE /volumes/{volume_id}`. Tolerate 404 (already gone). Guard so a failed
   machine delete doesn't orphan a volume and vice-versa.
5. **Return `volume_id`** on the `RuntimeHandle.extra` so the caller can persist it.

## Phase 2 — persist volume metadata on the agent

1. `cloud/db/models.py` `Agent`: add
   `volume_id: Mapped[str | None]`, `volume_region: Mapped[str | None]`,
   `volume_size_gb: Mapped[int | None]`.
2. Alembic migration in `cloud/alembic/versions/` (control-plane DB) — additive,
   nullable columns, no backfill required at migrate time.
3. `cloud/provisioning/workflow.py`: write `volume_id`/region/size onto the `Agent`
   row after `provision()` returns (read from `RuntimeHandle.extra`).
4. Plumb `volume_id` into `destroy()` (Phase 1.4) from the stored row.

## Phase 3 — de-hardcode the storage card

1. `cloud/api/agent_routes.py:706` — replace
   `"volume": {"mount": "/workspace", "size_gb": 1}` with real data: the stored
   `volume_id`/region/size (+ live `describe`/volume API if cheap) **and** the
   plugin's `file_storage_status` (`backend`, `durable`, location, used/max) pulled
   via the proxy (or cached metrics).
2. `cloud/ui/src/pages/AgentDetail.tsx` (lines ~31, ~272): widen the `volume` type
   and render durable/backend/usage, not a static "1 GB".

## Phase 4 — backfill existing fleet machines

Existing machines were created **without** a mount. For each live agent:

1. Ensure the volume exists (create by name in the machine's region).
2. `update_machine_env`-style config update that **also injects `mounts` + the
   `LUNA_FILES_*` env** (extend `update_machine_env`, or add `attach_volume`,
   so it merges `config["mounts"]` too, not just env). This recreates the machine
   with the volume attached. The old ephemeral `~/.luna/files` was never durable, so
   nothing real is lost; new writes land on the volume.
3. Persist `volume_id` on the row.
4. Admin surface (mirror 025's `migrate-all`):
   - `POST /api/admin/machines/{id}/attach-volume` (one agent; `dry_run`).
   - `POST /api/admin/machines/attach-volume-all` (fleet, staggered; per-agent
     `{attached, skipped, errors}` + `AuditLog`).
   - Idempotent: a machine that already has the mount is skipped.

## Phase 5 — containment (defense-in-depth, D7)

- Set the agent container root **read-only except `/workspace`** (Fly machine
  config / image). Keep `TMPDIR`/`LUNA_SCRATCH_DIR` on tmpfs (set in Phase 1.2).
- Verify the agent still boots, writes only under `/workspace`, and scratch goes to
  tmpfs. This is the layer that makes "write anywhere durable" physically impossible.

## Phase 6 — roll + verify

1. **Canary:** fresh agent on the 0.4.0 image with a volume. Dojo (real browser):
   write a file / take a `/browser` screenshot → it lands in Files under
   `/workspace/files`, `file_storage_status` says `durable=true, "mounted Fly
   volume"`. Then **roll the image** (`update_machine_image`) and **restart** →
   the file is still there.
2. **Cohort → fleet:** `attach-volume-all` (dry-run first) for existing machines,
   then `migrate-all` to the 0.4.0 image. Volumes persist across the roll.
3. **Verify** acceptance below across a cohort before declaring done.

## Acceptance criteria

- [ ] `provision()` creates/reuses a per-agent Fly volume in the machine's region,
      mounts it at `/workspace`, sets `LUNA_FILES_BACKEND=fly` +
      `LUNA_FILES_ROOT=/workspace/files` + `LUNA_FILES_DURABLE=1`.
- [ ] `volume_id` (+ region, size) persisted on the `Agent` row.
- [ ] Recreate reuses the same volume (no orphan, no data loss); a test proves no
      second volume is created.
- [ ] Agent delete removes the volume (no orphan billed volumes).
- [ ] A file written through `plugin-files` / the 001 `StorageProvider`
      **survives an image roll AND a machine restart** (canary-verified in a browser).
- [ ] `file_storage_status` → `durable=true`; the agent-detail storage card shows
      real volume + usage (no hardcoded "1 GB").
- [ ] Existing fleet machines backfilled via `attach-volume-all` (idempotent,
      staggered, audited, `dry_run` preview).
- [ ] Container root read-only except `/workspace`; `TMPDIR`/`LUNA_SCRATCH_DIR` on
      tmpfs.
- [ ] No luna-core / luna-plugins code change in this repo — Fly provisioning + env
      + control-plane only.

## Risks

- **Volume/machine region mismatch** → Fly rejects the mount. Always create the
  volume in the machine's resolved `region` (single source in `provision()`).
- **Config update drops the mount** → if any code path POSTs a partial config,
  the volume detaches. All updates must reuse the full `config` dict (as
  `update_machine_image`/`update_machine_env` already do); extend, don't replace.
- **Orphan volumes** → cost leak. Delete must run on agent delete and tolerate
  partial failures (machine gone but volume left, or vice-versa); add a periodic
  orphan-sweep check (volumes with no matching agent).
- **Single-writer** → never run >1 machine per agent against one volume. Not the
  case today; keep it that way.
- **Host failure (HA caveat)** → snapshots are the floor; document/plan optional R2
  working-set sync for irreplaceable data. Don't advertise HA.
- **Two `"storage"` registrants** → boot crash. Bake exactly one `plugin-files`;
  don't also bake a second storage plugin (carry-over of 025 D2).

## Open questions

1. **Default size + tiers:** start everyone at 1 GB and `extend` on demand, or tier
   by plan (1/5/20 GB)? Recommend 1 GB default + `POST /volumes/{id}/extend`.
2. **Snapshot retention:** 7 days enough, or longer for paid plans?
3. **R2 working-set sync:** ship a scheduled `fly → R2` backup now, or defer until a
   user has irreplaceable data? Recommend defer; snapshots cover the common case.
4. **Read-only rootfs blast radius:** confirm the Luna image + all baked plugins
   only write under `/workspace`/tmpfs before flipping rootfs to read-only fleet-wide
   (canary-gate Phase 5).
