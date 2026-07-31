# Plan 065 — Open/Resolved state on error groups (triage workflow)

## Problem
The admin Errors page (plan 051) shows one row per fingerprint group, but there is no
way to record "we fixed this". Once a defect is fixed, its group keeps sitting in the
list until its events age out of the time window, and there is no way to tell a
known-fixed error from a live one. We want a **fix/open state** so a group can be
marked resolved and, crucially, so a *resolved* group that starts erroring again is
flagged instead of silently blending back in.

## Why this is easy (the repeats are the point)
Errors repeating is exactly what makes this cheap: every repeat of the same defect
already collapses into **one fingerprint** at ingest (`compute_fingerprint` in
`cloud/observability/error_sink.py` — sha1 of kind + normalized message + route, with
ids/numbers/uuids normalized out). So state does not attach to individual events or to
`kind` — it attaches to the **fingerprint group**, i.e. exactly one status row per row
the admin sees in the table. Marking a group resolved once covers all past *and future*
repeats of that defect.

Unit of state: **fingerprint**, not `kind`. `kind` is a coarse category
(`proxy_502`, `js_error`, …) — resolving a whole kind would hide unrelated defects.
The user-facing "error type" in the UI table *is* the fingerprint group.

## Design

### 1. New table `error_group_status` (migration 0014)
One row per fingerprint that has ever been triaged. Groups with no row are `open`
(the default) — no backfill needed, and the ingest hot path is untouched.

```
fingerprint   TEXT PRIMARY KEY
status        TEXT NOT NULL            -- 'open' | 'resolved'
note          TEXT NULL                -- optional "fixed in 0.54.003" style note
resolved_at   TIMESTAMPTZ NULL        -- set when status flips to resolved
resolved_by   UUID NULL FK users.id ON DELETE SET NULL
created_at    TIMESTAMPTZ NOT NULL
updated_at    TIMESTAMPTZ NOT NULL
```

Model `ErrorGroupStatus` in `cloud/db/models.py` next to `ErrorEvent`.

### 2. Regression = derived, not stored
Because errors repeat, "resolved" must not mean "hidden forever". Effective status is
computed at query time in `list_groups`:

- no status row, or `status = 'open'` → **open**
- `status = 'resolved'` and `max(created_at) <= resolved_at` → **resolved**
- `status = 'resolved'` and `max(created_at) > resolved_at` → **regressed**

Deliberately **no auto-reopen on ingest**: the error sink (`record_error_event`) and
the agent ingest endpoint must stay write-only, best-effort, and storm-safe (plan 051
invariant — the sink never reads, never raises, never amplifies DB load). A derived
`regressed` state gives the same signal with zero writes on the hot path. Re-resolving
a regressed group simply bumps `resolved_at` forward.

### 3. API (`cloud/api/error_routes.py`)
- `PUT /api/admin/errors/{fingerprint}/status` — admin-only, same-origin, body
  `{status: 'open'|'resolved', note?: string}`. Upserts the row; sets
  `resolved_at = now()` / `resolved_by = admin.id` when flipping to resolved, clears
  them on reopen. 404 if the fingerprint has no events at all (typo guard). Returns
  the group's new status view. Declared **before** the `GET /{fingerprint}` catch-all.
- `GET /api/admin/errors` (`list_groups`): LEFT JOIN `error_group_status`
  (join key = the `group_by` key, so add the status columns to `group_by` — they're
  functionally dependent on fingerprint). Each group gains
  `status` (effective: open|resolved|regressed), `note`, `resolved_at`, `resolved_by`.
  New filter param `status=open|resolved|regressed` — applied in SQL via a HAVING /
  wrapped-subquery on the derived status so pagination stays correct. Default (no
  param) = all, preserving current behavior; the UI chooses its own default.
  `totals_by_severity` stays as-is; add `totals_by_status` for the header.
- `GET /api/admin/errors/{fingerprint}` (group detail): include the status object so
  the drawer can render/refresh it.

### 4. UI (`cloud/ui/src/pages/admin/ErrorsPage.tsx`)
- New **Status** column: chip `open` (default gray) / `resolved` (green) /
  `regressed` (red-outline, the loudest — a fixed thing came back).
- Status filter `Select` defaulting to **"Open + regressed"** (i.e. hide resolved),
  with All / Open / Resolved / Regressed options. Hiding resolved by default is the
  actual payoff: the page becomes a live triage queue.
- Drawer: `Resolve` button with optional note input; on a resolved/regressed group
  shows who/when/note and a `Reopen` button (and `Re-resolve` when regressed).
  After any status write, refetch the list.

### 5. Tests (`cloud/tests/test_errors.py`)
- resolve → group reports `resolved`; reopen → `open`; non-admin → 403; unknown
  fingerprint → 404.
- regression: resolve, then insert a newer event for the same fingerprint → list
  reports `regressed`; re-resolve → `resolved` again.
- `status=` filter returns only matching groups; default returns all.
- migration covered by the existing migration-fingerprint test flow (new table added
  to `_expected_core_columns` only if that check tracks it — verify; it currently
  tracks core-table columns, likely no change needed).

## Edge cases / accepted limitations
- **Fingerprint drift**: if the normalization in `compute_fingerprint` ever changes
  (plan 051 explicitly allows grouping to evolve), old status rows orphan — the
  "same" defect reappears as a new open group. Acceptable; worst case is re-triaging.
- **Message-variant escapes**: normalization strips ids/numbers/hex, but a genuinely
  differently-worded message for the same defect is a different fingerprint and needs
  resolving separately. Already true of grouping today; status doesn't change it.
- **Stale status rows**: statuses for fingerprints whose events aged out linger
  invisibly (list only shows groups with events in-window). Harmless; no GC needed.
- Multi-admin races on the upsert are last-write-wins — fine for an admin tool.

## Scope
~1 migration, ~30 lines model, ~60 lines API, ~80 lines UI, ~80 lines tests.
No changes to ingest paths, the error sink, the agent plugin, or luna itself.
