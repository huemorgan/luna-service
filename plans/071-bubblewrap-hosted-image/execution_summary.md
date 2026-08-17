# 071 — execution summary (2026-08-17)

**Delivered:** hosted tenant image `registry.fly.io/luna-agents:0.82.003` with
`bubblewrap 0.11.0-2+deb13u1`; set as main; all 9 machines that were on
0.82.002 upgraded.

## Changes
- luna-service `a581145` — `docker/luna-hosted.Dockerfile` runtime stage:
  `libpq-dev gcc curl bubblewrap`; luna submodule pin → 0.82.003.
- luna `81ba596` — plan 077, `__version__` 0.82.002 → 0.82.003 (release tag
  only; no code change), `plans/038-bubblewrap-in-image/execution_summary.md`.

## Rollout
1. `POST /api/admin/images/build?branch=main` → image `6247b72a-…`, GitHub run
   32048033299, build log shows bubblewrap installed in the runtime stage.
2. Canary `update-image` on vaselin-luna-bug-fixer (d8939d4b053528):
   `bwrap --version` → 0.11.0; `bwrap --unshare-all --uid 65534 … /usr/bin/id`
   → `uid=65534` (namespaces work as root on the Fly microVM).
3. `update-image` on vaselin-linearascent-promote (2861e43b4553e8, the tenant
   with plugin-inline-code-run installed): plugin probe
   `JailStatus(jail='jailed', backend='bwrap', reason='bwrap + user namespaces
   usable')`; `runner.run(...)` → `exit_code=0, backend='bwrap',
   stdout='hi 65534\nnonet OSError'` (jailed, non-root, no network).
4. Remaining 7 machines on 0.82.002 rolled 15 s apart; `set-main` 0.82.003.
5. Machine states after: identical to the pre-roll snapshot (5 started,
   4 stopped); agent_status unchanged for all 37 agents.

## Not done (deliberate)
- 27 machines still on 0.73.000 and 1 on 0.74.000-r1 were NOT migrated —
  they were not on 0.82.x before this plan; moving them is a separate rollout.
- `LUNA_INLINE_CODE_RUN_VENV_DIR` not set (optional; curated venv rebuilds
  ~10 s after each boot).
- No test-agent was created for 0.82.003 (canary on a real 0.82.002 machine
  instead).
