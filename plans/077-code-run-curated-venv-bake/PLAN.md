# 077 — Bake the code_run curated venv (data-stack packages, restart-proof)

Companion plan (plugin side): `plugin-inline-code-run/plans/004-curated-data-stack/plan.md`.
Builds on plan 035 (bubblewrap in the hosted image) and plan 019 (image-baked
plugin set).

## Goal

`code_run` (plugin-inline-code-run) should offer a real data/document stack —
numpy, pandas, matplotlib, docx/pptx, PDF-table extraction — **preinstalled,
offline, and instantly available on every tenant boot**, without shipping
megabytes in the plugin artifact and without re-downloading from PyPI when a
Fly machine restarts.

## Why this needs image work (the restart problem)

Facts established 2026-09-04 by reading luna-service + luna + the plugin:

1. **Fly machines get a fresh rootfs on every stop/start.** The only durable
   mount is the per-agent volume at `/workspace` (1 GB default,
   `cloud/runtime/fly_machines.py`), which holds user files. Everything else
   is rebuilt from the image at boot.
2. **The tenant scratch dir is deliberately ephemeral**: `files_env()` pins
   `LUNA_SCRATCH_DIR=/tmp/luna-scratch` and `TMPDIR` to it.
3. The plugin's curated venv lives at `LUNA_INLINE_CODE_RUN_VENV_DIR` when set,
   else under the plugin scratch dir (`venv_manager.default_venv_root`). No
   tenant sets the env var today ⇒ **the venv is rebuilt from PyPI on every
   machine restart**. A `prewarm()` daemon thread at plugin load hides it most
   of the time, but:
   - a `code_run` inside the boot window waits on pip (minutes for the
     expanded list);
   - every boot burns egress re-downloading the same wheels;
   - a PyPI outage or egress hiccup at boot degrades the tool for 15 min
     (`FAILURE_RETRY_SEC`) at a time.
4. **Runtime marketplace installs are ephemeral too**: `~/.luna/managed_plugins`
   sits on the rootfs, so a runtime-installed/upgraded plugin silently reverts
   at restart. The durable channel for plugin code on hosted is the
   **image-baked plugin set** (plan 019, `/opt/luna/plugin-set`,
   `LUNA_PLUGIN_SET_DIR`). plugin-inline-code-run has been added to the baked
   set (admin Plugin Set picker) — precondition for this plan.
5. The per-agent volume is the wrong home for the venv: 1 GB shared with user
   files, and a ~250 MB venv would eat a quarter of it per agent, N times
   across the fleet, instead of once in a shared image layer.

**Conclusion**: bake the venv into the image, exactly like the plugin set.
The plugin already has the escape hatch (`LUNA_INLINE_CODE_RUN_VENV_DIR`); the
image just has to build the venv and point the env var at it.

## Survival matrix (after this plan)

| Event                         | Plugin code                | Curated venv               |
|-------------------------------|----------------------------|----------------------------|
| Machine stop/start (fresh rootfs) | baked set — present at boot | baked layer — present at boot |
| Machine recreate / migrate    | same                       | same                       |
| Image deploy (promote)        | new baked set              | new baked venv, in lockstep |
| Scale-out (new machine)       | same                       | same                       |
| Runtime plugin upgrade (before next image) | managed_plugins until restart | baked venv may lack new packages → plugin pips the **delta** into scratch (graceful, ephemeral) and reports `curated_packages_missing` until the next image rolls |
| Self-hosted / local dev       | unchanged                  | unchanged — env var unset ⇒ build-on-first-use into scratch, `prewarm()` at load |

## Design

### Package list (plugin 0.4.0, `CURATED_PACKAGES`)

Existing: `pillow, pypdf, openpyxl, segno, fpdf2`
Added — data & charts: `numpy, pandas, matplotlib, seaborn`
Added — documents: `python-docx, python-pptx, pdfplumber`
Added — parsing/glue: `beautifulsoup4, lxml, pyyaml, tabulate, python-dateutil`

Deliberately excluded:
- `requests`/`httpx` — the jail has no network; shipping them invites
  confusing failures.
- `scipy`, `scikit-learn` — ~100 MB for rare chat-use demand; add on evidence.
- `plotly` — static export needs kaleido (bundled browser); matplotlib covers.

Names are **unpinned** (same policy as today): the venv key hashes the name
list, so plugin upgrades that don't touch the list never invalidate the venv,
and each image bake picks up current stable wheels.

### Venv-key contract (must not drift)

The plugin locates the venv at
`$LUNA_INLINE_CODE_RUN_VENV_DIR/curated-<key>/` where
`key = sha256("\n".join(sorted(packages)))[:12]`, ready iff
`bin/python` and `.curated-ready.json` (the marker) exist
(`venv_manager._key` / `cached_interpreter`). The bake script reproduces
exactly this: dir name, marker name, marker JSON shape
(`{"packages": [...], "tool": ..., "installed": [...], "failed": [...]}`).
The package list is **read from the baked plugin itself** (AST-parse of
`plugin_inline_code_run/settings.py::CURATED_PACKAGES`), so the image can
never bake a list that disagrees with the plugin version it ships — lockstep
by construction, no second source of truth.

### Changes — luna-service

1. **`scripts/bake_code_run_venv.py`** (new, stdlib-only driver):
   - `--set-dir /opt/luna/plugin-set --out /opt/luna/code-run-venvs`
   - finds `plugin_inline_code_run/settings.py` under the set dir; if the
     plugin isn't in this image's set, logs and exits 0 with an empty out dir
     (the ENV var then points at an empty root and the plugin falls back to
     scratch-build — non-fatal by design);
   - AST-parses `CURATED_PACKAGES`, computes the key, `python -m venv`,
     `pip install` the list, probes importability per package (same
     import-name map as the plugin), writes the marker;
   - **fails the build** (exit 1) if any package fails to install — an image
     must not ship a silently partial venv (the runtime fallback exists for
     genuine drift, not for a broken bake).
2. **`docker/luna-hosted.Dockerfile`**:
   - plugin-set stage: copy + run the new script after `bake_plugin_set.py`;
   - runtime stage: `COPY --from=plugin-set /opt/luna/code-run-venvs
     /opt/luna/code-run-venvs` and `ENV
     LUNA_INLINE_CODE_RUN_VENV_DIR=/opt/luna/code-run-venvs`.
   - Both stages are `python:3.12-slim` — the venv's `bin/python` symlink
     resolves to the same interpreter path/version in the runtime stage. If
     the base images ever diverge, the bake stage must match the runtime
     python minor version (the venv is not relocatable across minors).
   - The venv lands outside `/workspace` and `~/.luna`, so no per-tenant
     mount can shadow it (same reasoning as the plugin set).
3. **`plugin-set.toml` seed**: add `plugin-inline-code-run` pinned to 0.4.0 +
   sha256, so fallback builds (control plane unreachable) also bake it.

### Changes — plugin (0.4.0, detailed in its own plan)

- `CURATED_PACKAGES` expanded as above; import-probe map extended.
- Jail env: `MPLBACKEND=Agg` (headless matplotlib — without it the first
  `plt.savefig` may die probing GUI backends), `MPLCONFIGDIR` at the writable
  tmp, `OPENBLAS_NUM_THREADS=4` / `OMP_NUM_THREADS=4` (numpy's OpenBLAS
  spawns cpu-count threads and pre-allocates per-thread buffers — bounded so
  the jail's RLIMIT_AS/NPROC aren't tripped by import-time defaults).
- Tool description enumerates the packages **from the constant** (no
  hand-written copy to drift).
- Version stamps: `__init__.__version__` (authoritative), `pyproject.toml`,
  `luna-plugin.toml` → 0.4.0.

## Rollout

1. Plugin: land 0.4.0, full test suite, push (huemorgan2), publish to
   marketplaces.com.ai official.
2. luna-service: land bake script + Dockerfile + seed pin (sha256 from the
   published artifact), push.
3. Control plane: pin `plugin-inline-code-run` 0.4.0 in the image defaults
   (`rollout_image.py pin` or admin UI) — pin **before** build (build
   snapshots defaults at image-record creation).
4. Build image (`rollout_image.py build`, GitHub `build-luna-image.yml`),
   using luna main's current `__version__` (bump luna only if that version is
   already built — per the workflow's verify step).
5. Promote + migrate fleet (`rollout_image.py promote`), `verify` against Fly.
6. Tenant verification: `code_run` importing numpy/pandas/matplotlib returns
   `ok: true, backend: bwrap` with no `curated_packages_missing`, and the run
   report shows `reused: true` (venv found, not built) immediately after a
   machine restart.

## Risks / notes

- **Image size**: +~250 MB layer (numpy/pandas/matplotlib dominate). Shared
  across the fleet; pulled once per machine per image version. Accepted.
- **Wheel platform**: workflow builds on ubuntu-latest amd64, Fly machines are
  amd64 — wheels match. If arm64 machines ever appear, the bake must be
  per-arch (buildx) — out of scope.
- **First image build is slower** (~2–4 min pip). Subsequent builds hit
  Docker layer cache unless the plugin pin changed.
- **List drift between plugin upgrade and image roll** is expected and
  self-healing (delta-pip fallback + `curated_packages_missing` surfaced to
  the model; next image bake restores lockstep).
- The 15-min failure cache (`FAILURE_RETRY_SEC`) still governs scratch-build
  fallback on no-egress hosts — unchanged.
