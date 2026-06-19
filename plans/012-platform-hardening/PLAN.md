# Plan 012 — Platform Hardening

A bundle of small, independent reliability and safety items. Each section
is shippable on its own; do them in order unless something is on fire.
The marketing website is NOT here — it already has its own plan and
execution under `plans/website/`.

Origin: the June 2026 debugging sessions. Every item below is a bug class
we actually hit (stuck `provisioning` agents, 409 machine-name conflicts,
silent provisioning failures discovered by staring at the dashboard) or a
risk we're knowingly carrying (open secrets, unmetered LLM spend).

---

## 012.1 — Reconciliation loop (highest value)

### Problem

The `agents` table and Fly reality drift apart. Cases we hit in production:

- Agent stuck in `provisioning` forever because the provisioning coroutine
  crashed *outside* its try/except (the `CLOUD_RUNTIME=fly` ValueError).
- Fly machine in `created`/`failed` state with the agent's name, causing
  `409 already_exists` on retry (now patched point-wise, but the class
  remains).
- Machine destroyed manually on Fly while the agent row still says
  `running`.
- The dashboard fakes failure detection with a UI-side heuristic
  ("provisioning for > 5 min == Setup failed") instead of knowing.

Point-fixes patch one path at a time. A reconciler absorbs the whole class.

### Design

A periodic background task in the control plane (asyncio task started in
`cloud/main.py` lifespan, every 60s):

1. Fetch all Fly machines (`FlyMachinesRuntime.list_machines()` — one API
   call) and all agent rows with `runtime_ref IS NOT NULL OR status IN
   ('provisioning', 'running', 'stopped')`.
2. For each agent, compare DB status vs Fly state:

| DB says | Fly says | Action |
|---|---|---|
| `running` | machine missing | mark `error`: "Machine no longer exists" |
| `running` | `stopped`/`suspended` | mark `stopped` |
| `stopped` | `started` | mark `running` |
| `provisioning` for > 10 min | anything | mark `error`: "Provisioning timed out", destroy stale machine if present |
| `error` | `started` + healthy | mark `running`, clear error (self-heal) |
| no row | machine with `luna-` prefix | log orphan; surface in admin Machines page (do NOT auto-destroy) |

3. Every transition writes an `audit_log` row (`reconciler.*` actions,
   actor_type=system) and emits a log line.

Remove the 5-minute `stuckProvisioning` heuristic from `Dashboard.tsx` —
the backend now owns failure detection; the UI just renders `status` +
`error_message`.

### Non-goals

- Auto-destroying orphan machines (flag only — a bug here deletes user data).
- Reconciling tenant schemas (covered by 012.2 for test agents only).

### Exit criteria

- Kill a machine via `flyctl` → dashboard shows `error` with message within 2 min.
- Break provisioning (bad env) → agent lands in `error` within 10 min, no UI heuristic involved.
- Orphan machine appears in admin Machines page flagged as orphaned.

---

## 012.2 — Test agent lifecycle & cleanup

### Problem

Every "Test Agent" click creates: an `agents` row, a Fly machine, and a
tenant Postgres schema. We've created at least 6 test agents this month.
Deleting from the dashboard destroys the machine, but the tenant schema
(`luna_user_*`) survives forever, and nothing prevents test agents from
piling up.

### Design

1. **Mark them**: add `is_test: bool` to `Agent` (set by the
   `/test-agent` endpoint). Test agents render with a "test" badge in
   dashboard + admin machines list.
2. **Full teardown**: agent deletion (for test agents) also drops the
   tenant schema via `destroy_tenant_schema`. For regular agents keep
   current behavior (schema survives — that's user data; see Hard Rules).
3. **TTL sweep**: reconciler (012.1) flags test agents older than 7 days;
   admin Machines page gets a "clean up stale test agents" button that
   destroys them (machine + schema + row) after explicit click. No silent
   auto-delete.
4. **Retry honors origin image**: store `image_id` on the agent at
   creation; `/retry` re-provisions test agents with their original image
   via `provision_luna_for_account_with_image` instead of silently falling
   back to main.

### Exit criteria

- Deleting a test agent leaves zero machines, zero schema, zero rows.
- Retry on a failed test agent uses the image it was created from.
- Stale test agents (>7d) appear flagged; one click removes them.

---

## 012.3 — Failure alerting

### Problem

Provisioning failures, build failures, and machine crashes are discovered
by looking at the dashboard. Nobody is notified.

### Design

Minimal: a `notify(subject, body)` helper in the control plane that posts
to a Slack incoming webhook (`CLOUD_ALERT_SLACK_WEBHOOK` env var; we
already have a Slack app). If the var is unset, it logs and returns.

Call it from:

- provisioning failure paths in `workflow.py` (both functions)
- `build_complete` webhook when `status == "failed"`
- reconciler transitions into `error` (012.1)
- unhandled exceptions in the provisioning background task

One alert per event, no dedup/batching yet. Include agent slug, error
message, and a link to the admin dashboard.

### Non-goals

- Email, PagerDuty, on-call rotations, alert dedup — later, if ever.

### Exit criteria

- Break a provision on purpose → Slack message arrives with the error.

---

## 012.4 — Cost metering (control-plane side only)

### Problem

Every tenant Luna runs on our Anthropic/OpenAI keys. We have zero
visibility into per-account spend. One enthusiastic user burns real money
silently. This must land before any open signup; billing (Stripe) stays
punted, but metering is its prerequisite anyway.

### Dependency — NOT ours to build

Per-call cost tracking is **Luna Phase 018** (`plugin-cost` — already
planned in `luna/plans/018-cost-rate-limiter/PLAN.md`: every LLM call
priced and persisted in `plugin_cost_records`, with cost tools and a
Costs UI). We do not implement any of that here, and we do not touch the
Luna codebase in this plan.

What the control plane needs from 018 is one small addition — a
service-facing summary endpoint — proposed in
`plans/luna-proposals/018.1-usage-api-for-hosted.md` (proposal in THIS
repo; the Luna project decides if/when to adopt it). 012.4 is blocked
until 018 + that endpoint ship in a Luna image.

### Design (control plane only)

1. Nightly task calls each running agent's usage-summary endpoint via the
   existing trusted proxy, stores per-account daily rollups in a
   `usage_rollups` table.
2. **Admin UI**: per-account spend column on the admin Machines page +
   a simple "spend this month" list. No tenant-facing UI yet.
3. **Soft alarm**: reuse 012.3 — Slack alert when an account crosses
   `CLOUD_SPEND_ALERT_USD` (default 20) in a calendar month.

### Non-goals

- Enforcement/caps, billing, tenant-facing dashboards, streaming-accurate
  realtime numbers. Daily granularity is fine.
- Anything inside the Luna codebase.

### Exit criteria

- Admin page shows believable per-account month-to-date dollar spend.
- Crossing the threshold fires a Slack alert.

---

## 012.5 — Secrets hygiene

### Problem

Live credentials are spread across `.env` (Fly token, Render API key, DB
passwords, LLM keys, Google OAuth secret), a GitHub PAT that has appeared
in terminal scrollback and in a Render env var, and a skill file with a
production DB password. The repo is private and single-user today, but
every one of these is a standing liability and rotation is undefined.

### Design (a checklist, not code)

1. **Rotate now**: GitHub PAT (it leaked into terminal output), Fly API
   token, Render API key. Update Render env vars + GitHub secrets as the
   only storage for production values.
2. **Local `.env` slimming**: local dev keeps only what local dev needs
   (docker-local runtime needs no Fly/Render creds). Production-only
   values live in Render env vars exclusively.
3. **Pre-commit guard**: add `gitleaks` (or a simple grep hook) to block
   accidental commits of `sk-ant-`, `rnd_`, `FlyV1`, `ghp_`, `GOCSPX-`
   patterns. `.env` is already git-ignored — verify with
   `git check-ignore` and add a CI check.
4. **Vault root key story**: document (one page in `vision/`) what happens
   if `CLOUD_VAULT_ROOT_KEY` leaks — rotation requires re-encrypting every
   tenant vault; write the runbook now while there are ~3 tenants, not at
   300. Defer KMS as already planned.
5. **One-time keys**: delete the `FLY_IO_ONETIME_KEY*` entries from `.env`
   (consumed or dead).

### Exit criteria

- Old PAT/tokens revoked and confirmed non-working.
- `gitleaks` hook blocks a test commit containing a fake `sk-ant-` key.
- Vault-key-rotation runbook exists.

---

## Suggested order & sizing

| Item | Size | Depends on |
|---|---|---|
| 012.1 reconciler | 1–2 days | — |
| 012.2 test agent cleanup | 1 day | 012.1 (sweep) |
| 012.3 alerting | ½ day | — (012.1 calls it) |
| 012.5 secrets | ½ day | — (do the rotation immediately) |
| 012.4 cost metering | 1–2 days | Luna 018 + 018.1 shipped in an image |

Not included here (Luna-side work — proposals live in this repo under
`plans/luna-proposals/`; the Luna project owns whether/when to do them):

- **Onboarding double-greeting fix** —
  `plans/luna-proposals/005.925-onboarding-double-greeting.md`
- **Usage API for hosted mode** —
  `plans/luna-proposals/018.1-usage-api-for-hosted.md`

Also not included: agent sleep/wake (real economics win but a meaty
phase of its own — proxy wake path exists, needs suspend policy, wake
latency UX, and reconciler awareness; propose as Plan 013), billing
(post-metering), tenant-facing audit log.
