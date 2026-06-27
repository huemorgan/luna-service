# 025.5 — Persistent files: E2E scenarios

These are LLM-run scenarios (you are the test runner). Coded unit tests for the
runtime live in `cloud/tests/test_fly_volumes.py`; these cover the parts that need
a real environment / browser.

## S1 — New agent gets a persistent volume (runtime, requires Fly)

**Pre:** `CLOUD_RUNTIME=fly-machines`, `FLY_API_TOKEN` set, `plugin-files 0.4.0`
baked into the main image.

1. Provision a fresh agent (or `POST /api/admin/images/{id}/test-agent`).
2. In the Fly dashboard / API, confirm a volume named `luna_data_<slug>` exists in
   the machine's region, encrypted, and the machine config has
   `mounts: [{path: /workspace}]`.
3. In the agent, run a tool that writes a file (or take a `/browser` screenshot).
   Confirm it lands under `/workspace/files` and `file_storage_status` reports
   `durable=true, "mounted Fly volume"`.

**Pass:** volume exists + mounted + file written under `/workspace/files`,
`durable=true`.

## S2 — Files survive an image roll AND a restart (the headline)

1. From S1, note the file you wrote.
2. Roll the machine image (`POST /api/admin/machines/{id}/update-image`) to a new
   build, OR restart the machine.
3. After it comes back healthy, open the same file via the Files UI / `file_read`.

**Pass:** the file is still there with identical contents. (This is the property
that distinguishes a volume from the old ephemeral `~/.luna/files`.)

## S3 — Recreate reuses the same volume (no data loss, no orphan)

1. From S1, force a machine recreate (put it in a bad state, or delete+reprovision
   via the provision path that destroys-then-recreates).
2. Confirm provision re-attaches the **same** `luna_data_<slug>` volume (same id),
   does not create a second volume, and the file from S1 is still present.

**Pass:** one volume, same id, file intact.

## S4 — Delete cleans up the volume (no orphan billing)

1. Delete the agent (`DELETE /api/agents/{id}`).
2. Confirm both the machine and the `luna_data_<slug>` volume are gone in Fly.

**Pass:** no orphan volume left.

## S5 — Storage card shows real volume info (browser)

1. Sign in, open the agent detail page.
2. Look at the Storage section → Volume row.

**Pass (provisioned via 025.5):** shows `/workspace · N GB · persistent (Fly
volume) · <region>` (and usage if available) — NOT a hardcoded "1 GB".
**Pass (legacy / no volume):** shows `/workspace · ephemeral (no volume — not
persistent)` in amber.

## S6 — Backfill an existing machine (admin)

1. On a machine that predates 025.5 (no mount), call
   `POST /api/admin/machines/{id}/attach-volume` with `{"dry_run": true}` →
   confirm `would_attach: true`.
2. Call it again without `dry_run` → confirm it attaches the volume + files env and
   the machine comes back healthy.
3. Call once more → confirm it is now `skipped: true` (idempotent).
4. `POST /api/admin/machines/attach-volume-all` `{"dry_run": true}` lists every
   machine with `has_volume`.

**Pass:** attach is idempotent, audited (`machine.volume_attached`), and the agent
detail card flips to "persistent".

---

## Production rollout findings (2026-06-27)

Executed live against `luna-agents` (Fly) + `luna-service` control plane. Three
Fly behaviours that the first implementation got wrong, fixed during rollout:

1. **Volume names cap at 30 chars** (`[a-z0-9_]`). `luna_data_<slug>` overflowed
   for longer slugs (400 on create). Fix: `luna_<trunc-slug>_<6-char-hash>`,
   deterministic so provision/attach/destroy resolve the same volume.
2. **A volume is only mountable from a machine in its zone.** A fresh volume
   lands in an arbitrary zone, so you cannot add a mount to an existing,
   zone-pinned machine ("volume does not exist"). Backfill therefore **destroys
   and re-provisions** the machine (provision creates the volume first and Fly
   co-locates the new machine in its zone). The agent's durable state
   (per-agent Postgres + R2) is untouched; only the ephemeral machine is
   recreated. See `_recreate_with_volume` in `admin_routes.py`.
3. **Deleted volumes linger** in `pending_destroy` / `scheduling_destroy` with
   the same name. `_ensure_volume` must reuse only the `created` state, else it
   grabs a half-deleted volume → "volume not found" at machine-create. (Fly
   volume names need not be unique, so creating a fresh same-named volume while
   an old one drains is fine.)

Outcome: all live agents migrated to `0.19.002` (plugin-files 0.4.0) each with a
1 GB `/workspace` volume; dead/stale test machines were skipped; deleting an
agent cleaned up its volume.
