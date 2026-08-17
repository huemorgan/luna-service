# 071 — bubblewrap in the hosted tenant image (code_run kernel jail)

## Problem
`plugin-inline-code-run` (`code_run`, marketplace `official`, 0.1.1) executes
agent-written Python only inside a kernel jail — bubblewrap on Linux. The
hosted tenant image has no `bwrap` binary, so on every tenant the tool loads,
shows in the toolkit, and refuses every call before Python starts:

    code_run refused: no usable jail on this host (bwrap: bwrap not on PATH; ...)

Confirmed 2026-08-17 on a tenant running **0.82.002**. Luna's own `Dockerfile`
(luna plan 038, 0.82.002) already installs bubblewrap, but the tenant image is
NOT built from it — the "Build Luna Image" workflow builds
`docker/luna-hosted.Dockerfile`, whose runtime stage installs only
`libpq-dev gcc curl` (build log of run 32038420169, image tag 0.82.002).

## Change (one word)
`docker/luna-hosted.Dockerfile`, runtime stage:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl bubblewrap \
    && rm -rf /var/lib/apt/lists/*
```

Nothing else. The container runs as root on the Fly machine, so bwrap creates
its namespaces directly — no sysctl, no setuid, no seccomp/AppArmor changes.
The plugin's full suite (101 tests, incl. the attack suite) is green on
`python:3.12-slim` (Debian 13, bubblewrap 0.11.0), the same base image.

## Rollout
1. Commit the Dockerfile change on luna-service main.
2. Bump luna `__version__` (0.82.003; luna plan 077) — the workflow's "Verify version" step
   requires the tag to match the on-disk version, so a new tag needs a bump.
   (Alternatively rebuild 0.82.002 with a qualified tag; a clean bump is simpler.)
3. `POST /api/admin/images/build?branch=main` (dispatches "Build Luna Image" for 0.82.003).
4. test-agent → set-main → `update-image` on the machines currently on 0.82.002.
   Machines still on 0.73.000 / 0.74.000-r1 are left alone (separate rollout decision).

## Optional (tenant env)
`LUNA_INLINE_CODE_RUN_VENV_DIR=/workspace/.code-run-venvs` — puts the plugin's
curated venv (pillow/pypdf/openpyxl/segno/fpdf2, ~15 MB) on the volume so it
survives machine restarts instead of rebuilding (~10 s, needs egress) on the
first `code_run` after each boot. Not required.

## Verify
- `fly ssh console -a luna-agents -s <machine> -C "bwrap --version"` prints a version.
- In the tenant chat, `code_run` with `print("hello")` returns
  `ok: true, backend: "bwrap"`; the plugin's refusal disappears.

## Not in scope
Any plugin change (0.1.1 already handles the bwrap path), Render/control-plane
changes, unprivileged-userns sysctls (only relevant if Luna ever runs non-root).
