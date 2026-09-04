# 077 — Execution summary (code_run curated venv bake)

Executed 2026-09-04. Plugin-side summary:
`luna-plugins/plugins/plugin-inline-code-run/plans/004-curated-data-stack/execution_summary.md`.

## Outcome

Image **0.92.027** ships the curated venv as an image layer at
`/opt/luna/code-run-venvs/curated-a07968e04f2c` (all 17 packages installed and
import-probed at build time, 28 s), with
`ENV LUNA_INLINE_CODE_RUN_VENV_DIR=/opt/luna/code-run-venvs`. The plugin finds
a ready venv on every boot — no PyPI at tenant runtime, restart-proof.

## Commits (luna-service, huemorgan/luna-service main)

- `d8803d4` — `scripts/bake_code_run_venv.py` (AST-parses the baked plugin's
  `CURATED_PACKAGES`, builds the venv at the keyed path, writes the
  `.curated-ready.json` marker, fails the build on any missing package);
  Dockerfile plugin-set stage runs it + runtime stage copies
  `/opt/luna/code-run-venvs` and sets the ENV var; `plugin-set.toml` seed pin
  plugin-inline-code-run 0.4.0 (sha256 `086c3196…`); PLAN.md.
- `f39e4d8` — fix 1: `docker/luna-hosted.Dockerfile.dockerignore` starts from
  `**` (ignore all) and must whitelist every file the build COPYs — added
  `!scripts/bake_code_run_venv.py`. Without it the docker build dies with
  "not found" even though the file is in the repo.
- `35e98ee` — fix 2: `bake_plugin_set.py` unpacks artifacts **flat**
  (`<set-dir>/<pkg>/…`, the zip's single top-level dir is the package), but the
  finder globbed `*/<pkg>/settings.py` (one extra level). The venv bake then
  "skipped" silently (exit 0, by-design fallback for plugin-not-in-set) — the
  0.92.026 image shipped WITHOUT the venv while looking green. Finder now
  checks the flat layout first.
- `886ab77` — `rollout_image.py` gained `rebake` and `audit` subcommands
  (rollout tooling; see lessons).

## Rollout timeline

1. Plugin 0.4.0 published to marketplaces.com.ai official; pinned into the
   image defaults via `rollout_image.py pin` (before build — build snapshots
   defaults at image-record creation).
2. Build attempt `0.92.025-r3` via `rollout_image.py build --version …-r3`:
   **failed 3×**. Attempt 1+3: the workflow's "Verify version matches" step
   compares the dispatched version against luna main's on-disk `__version__` —
   a `-rN` tag can only be built through the **rebake** path
   (`POST /images/rebake`, or a manual `gh workflow run` passing
   `base_version=<raw>`), never `build --version <base>-rN`. Attempt 2: the
   dockerignore miss (fix 1). Meanwhile luna main moved to 0.92.026.
3. `0.92.026` built green but with the venv bake silently skipped (fix 2's
   bug) — verified by reading the run's `[bake-code-run-venv]` lines. Never
   promoted.
4. Luna main bumped to 0.92.027 (a concurrent session's work: plans 102/103);
   its build at 19:55Z ran with both fixes:
   `[bake-code-run-venv] packages (17) … ready: /opt/luna/code-run-venvs/curated-a07968e04f2c`.
   0.92.027 promoted to MAIN; fleet migrated.
5. Defaults note: at 19:35Z the admin default plugin_set was edited in the
   admin UI (browser IP) from 17 → 15 entries — plugin-chat-ui and
   plugin-feedback removed. Not this plan's doing; flagged to Roy.

## Lessons / operational contracts (read before the next image change)

- **`build --version` must equal luna main's `__version__`.** Same-version
  rebuilds (new plugin set / Dockerfile) go through rebake, which auto-tags
  `{base}-r{n}` and passes `base_version` to the workflow. Now scripted:
  `python scripts/rollout_image.py rebake`.
- **A failed GitHub run can be re-dispatched directly** with the same image
  record: `gh workflow run build-luna-image.yml -f version=<tag>
  -f image_id=<record-uuid> -f branch=main -f base_version=<raw-version>`.
  The build-complete webhook flips the record failed→built unconditionally.
- **`docker/luna-hosted.Dockerfile.dockerignore` is allow-list style.** Any
  new COPY into the image needs a `!` entry there; the repo-root .dockerignore
  is NOT what this build uses (BuildKit prefers `<dockerfile>.dockerignore`).
- **Plugin-set layout is flat**: `<set-dir>/<package_dir>/…`. Anything walking
  the baked set must expect that.
- **Silent-skip paths hide failures**: the bake script's plugin-not-in-set
  exit-0 branch masked the layout bug for a whole image build. When verifying
  an image, grep the run log for `[bake-code-run-venv] ready:` — not just a
  green run.
- **Loki job logs are flaky** (empty results minutes after job completion);
  `rollout_image.py audit` reads the audit_log table instead — that is the
  reliable oracle for what actually happened (defaults edits, build triggers,
  webhook callbacks, actor IPs).
- **One-off `python -c` jobs with exec'd base64 are not trustworthy** — one
  "succeeded" in 8 s with no audit row and no dispatch. Put tooling in
  `rollout_image.py` subcommands instead; the control plane auto-deploys on
  push to main (live in ~3 min), so new subcommands are runnable quickly.

## Verification

- Build-time: all 17 packages import-probed inside the image (build log).
- Fleet: `rollout_image.py verify --version 0.92.027` against Fly (machines
  tally on the new tag).
- Tenant-level check (post-migration): `code_run` importing
  numpy/pandas/matplotlib returns ok with `reused: true` and no
  `curated_packages_missing` right after a machine restart.
