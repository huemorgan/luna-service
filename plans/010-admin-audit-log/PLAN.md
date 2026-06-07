# Plan 010 — Admin Audit Log & Changelog UI

## Problem

Admin actions on images, machines, and users are partially logged to an
`audit_log` table, but:

1. **No UI** — nobody can see the logs without querying Postgres directly.
2. **No IP address** — we can't trace where an action originated.
3. **Incomplete coverage** — `build_image`, `build_complete` (webhook), and
   `check_update` aren't logged. The build lifecycle has no audit trail from
   trigger to completion.
4. **No filtering/search** — even if someone queries the DB, the action names
   aren't standardized and there's no text-search story.
5. **No before/after snapshots** — config changes store the patch but not what
   the value was *before* the change, making it hard to answer "what was it set
   to before someone changed it?"

Platforms like Vercel, Infisical, and Render all expose an Activity Log /
Audit Log in their admin dashboards with filtering by actor, action type, date
range, and resource. This is table stakes for any multi-admin platform.

## Goals

- Every admin mutation is logged with who, what, when, from where, and the
  before/after state when applicable.
- A dedicated "Changelog" section in the admin sidebar shows a filterable,
  paginated timeline of all logged events.
- The system is append-only — no updates or deletes on audit rows.

## Non-goals (for this phase)

- Tenant-facing audit logs (customer sees their own agent activity) — future.
- SIEM/webhook streaming of events — future.
- CSV/JSON compliance export — future (trivial to add once the data is clean).
- Cryptographic hash chain for tamper evidence — overkill at current scale.

---

## Design

### 1. Schema changes to `AuditLog`

Add three columns to the existing model:

| Column          | Type       | Purpose                                          |
|-----------------|------------|--------------------------------------------------|
| `actor_ip`      | `Text`     | IP address of the request (from X-Forwarded-For) |
| `before_state`  | `JSONB`    | Snapshot of the resource *before* the mutation    |
| `after_state`   | `JSONB`    | Snapshot of the resource *after* the mutation     |

Add two indexes:

- `ix_audit_log_action` on `(action)` — filter by action type.
- `ix_audit_log_created_at` on `(created_at DESC)` — efficient pagination.

The existing `ix_audit_log_account_id` index stays.

### 2. Standardized action names

Adopt a `resource.verb` convention. Rename existing actions for consistency
and add missing ones:

| Action                       | Trigger                      | Currently logged? |
|------------------------------|------------------------------|:-:|
| `admin.added`                | Add admin                    | Yes |
| `admin.removed`              | Remove admin                 | Yes |
| `image.config_updated`       | Update image config          | Yes |
| `image.deleted`              | Delete image                 | Yes |
| `image.promoted_to_main`     | Set as main                  | Yes |
| `image.build_triggered`      | Trigger build                | **No** |
| `image.build_completed`      | Webhook: build success       | **No** |
| `image.build_failed`         | Webhook: build failure       | **No** |
| `machine.image_updated`      | Update single machine image  | Yes |
| `machine.migrate_all`        | Migrate all machines         | Yes |
| `agent.test_created`         | Create test agent from image | Yes |

### 3. IP capture

Create a FastAPI dependency `get_client_ip(request: Request) -> str` that
reads `X-Forwarded-For` (Render sets this), falling back to
`request.client.host`. Inject it into every admin endpoint that writes an
audit row.

For the webhook endpoint (`build_complete`), record the IP as the actor is
"system/github-actions" — no user, but the source IP is still useful.

### 4. Before/after snapshots

For mutations that change state:

- **`image.config_updated`**: `before_state` = config before patch,
  `after_state` = config after patch.
- **`image.promoted_to_main`**: `before_state` = `{previous_main_image_id, previous_main_version}`,
  `after_state` = `{new_main_image_id, new_main_version}`.
- **`admin.added` / `admin.removed`**: `before_state` = `{is_admin: false}`,
  `after_state` = `{is_admin: true}` (and vice versa).
- **`machine.image_updated`**: `before_state` = `{version: old}`,
  `after_state` = `{version: new}`.

Actions that create or destroy a resource store the resource snapshot in
`after_state` (create) or `before_state` (delete).

### 5. Helper function

Extract a reusable helper to reduce boilerplate:

```python
async def _audit(
    db: AsyncSession,
    *,
    action: str,
    actor: User | None = None,
    actor_ip: str | None = None,
    target: str | None = None,
    account_id: uuid.UUID | None = None,
    metadata: dict | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
):
    db.add(AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_ip=actor_ip,
        action=action,
        target=target,
        account_id=account_id,
        metadata_=metadata,
        before_state=before_state,
        after_state=after_state,
    ))
```

### 6. API endpoint

```
GET /api/admin/audit-log
```

Query parameters:

| Param      | Type   | Default   | Description                               |
|------------|--------|-----------|-------------------------------------------|
| `page`     | int    | 1         | Page number (1-indexed)                   |
| `per_page` | int    | 50        | Items per page (max 100)                  |
| `action`   | str?   | —         | Filter by action name (exact or prefix)   |
| `actor_id` | uuid?  | —         | Filter by actor user ID                   |
| `from`     | iso?   | —         | Events after this timestamp               |
| `to`       | iso?   | —         | Events before this timestamp              |
| `target`   | str?   | —         | Filter by target resource ID              |
| `q`        | str?   | —         | Full-text search in action + metadata     |

Response:

```json
{
  "items": [
    {
      "id": "uuid",
      "action": "image.promoted_to_main",
      "actor": { "id": "uuid", "name": "Roy Man", "email": "...", "avatar_url": "..." },
      "actor_ip": "1.2.3.4",
      "target": "image-uuid",
      "metadata": { "version": "0.5.12" },
      "before_state": { "previous_main": "0.5.11" },
      "after_state": { "new_main": "0.5.12" },
      "created_at": "2026-06-07T15:30:00Z"
    }
  ],
  "total": 142,
  "page": 1,
  "per_page": 50
}
```

The endpoint joins `users` to hydrate `actor` details so the UI doesn't need
a second call.

### 7. Admin UI — Changelog page

**Sidebar entry**: Add "Changelog" with a `ScrollText` (or `History`) icon to
`NAV_ITEMS` in `AdminLayout.tsx`, below "Machines".

**Page layout** (`ChangelogPage.tsx`):

```
┌──────────────────────────────────────────────────────┐
│  Changelog                                           │
│                                                      │
│  [Action ▾]  [Actor ▾]  [Date range]  [Search... ]   │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ 🟢 image.promoted_to_main                      │  │
│  │ Roy Man · 1.2.3.4 · 2 hours ago                │  │
│  │ v0.5.12 promoted to main (was v0.5.11)         │  │
│  ├────────────────────────────────────────────────┤  │
│  │ 🔵 image.build_triggered                       │  │
│  │ Roy Man · 1.2.3.4 · 3 hours ago                │  │
│  │ Build triggered for v0.5.12                     │  │
│  ├────────────────────────────────────────────────┤  │
│  │ 🟡 machine.migrate_all                         │  │
│  │ Roy Man · 5.6.7.8 · yesterday                  │  │
│  │ 4 machines updated to v0.5.11, 0 errors        │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  ◀ Page 1 of 3 ▶                                     │
└──────────────────────────────────────────────────────┘
```

**Design details**:

- Each entry is a card showing the action badge (color-coded by category),
  human-readable description, actor avatar + name, IP, and relative timestamp.
- Clicking a card expands it to show `before_state` / `after_state` diff and
  full `metadata` JSON.
- Color coding: green = create, blue = update/promote, yellow = migrate/bulk,
  red = delete, gray = system/webhook.
- Filters persist in URL query params (shareable, back-button friendly).
- Infinite scroll or pagination — start with pagination, simpler and matches
  audit log convention.

**Human-readable descriptions**: A mapping from action to template string
renders each event as a sentence:

```typescript
const ACTION_LABELS: Record<string, (m: any) => string> = {
  'admin.added':              m => `${m.email} added as admin`,
  'admin.removed':            m => `${m.email} removed from admins`,
  'image.build_triggered':    m => `Build triggered for v${m.version}`,
  'image.build_completed':    m => `Build completed for v${m.version}`,
  'image.build_failed':       m => `Build failed for v${m.version}: ${m.error}`,
  'image.config_updated':     m => `Config updated for v${m.version}`,
  'image.promoted_to_main':   m => `v${m.version} promoted to main`,
  'image.deleted':            m => `Image v${m.version} deleted`,
  'machine.image_updated':    m => `Machine updated to v${m.version} (${m.agent})`,
  'machine.migrate_all':      m => `${m.updated} machines migrated to v${m.version}`,
  'agent.test_created':       m => `Test agent "${m.agent_slug}" created on v${m.version}`,
};
```

---

## Implementation plan

### Phase 1 — Schema & migration

1. Add `actor_ip`, `before_state`, `after_state` columns to `AuditLog` model.
2. Add indexes on `action` and `created_at DESC`.
3. Generate and run Alembic migration.

### Phase 2 — Backend audit coverage

1. Create `_audit()` helper in `admin_routes.py`.
2. Create `get_client_ip` dependency.
3. Retrofit all existing `AuditLog(...)` calls to use `_audit()` with IP and
   before/after snapshots.
4. Add audit logging to `build_image` (on trigger) and `build_complete`
   (on webhook, with system actor).
5. Rename action strings to the standardized `resource.verb` format.
6. Add `GET /api/admin/audit-log` endpoint with filters and pagination.

### Phase 3 — Frontend

1. Create `ChangelogPage.tsx` with filter bar and paginated event list.
2. Add "Changelog" to admin sidebar in `AdminLayout.tsx`.
3. Add route in the admin router.
4. Build the expandable card component with before/after diff view.

### Phase 4 — Polish

1. Relative timestamps ("2 hours ago") with exact tooltip on hover.
2. Color-coded action badges.
3. Empty state when no events match filters.
4. Ensure the page handles hundreds of events without performance issues
   (server-side pagination does the heavy lifting).

---

## Reference: how others do it

| Platform    | Key feature we're borrowing                                 |
|-------------|-------------------------------------------------------------|
| **Vercel**  | Activity Log: chronological timeline, actor + event type + time, CSV export |
| **Infisical** | Filterable table with actor/action/source/date combos, expandable metadata |
| **Render**  | Deploy events timeline with status badges and duration      |
| **Cloudflare** | Audit Log with IP, actor, resource, action, date range filtering |
| **Vercel Enterprise** | SIEM streaming (future for us)                     |

The common pattern: **filterable paginated timeline, actor + action + resource + timestamp, expandable detail view.** That's exactly what we're building.

---

## Open questions

1. **Retention** — do we want to auto-purge logs older than N months? At our
   current scale (single-digit admins) this is not urgent. Punt.
2. **Webhook actor** — for `build_complete`, store `actor_user_id = NULL` and
   set `metadata.actor_type = "system"`. The UI renders this as "GitHub Actions".
3. **Read-only enforcement** — should we add a DB trigger blocking UPDATE/DELETE
   on `audit_log`? Nice-to-have, not blocking for this phase.
