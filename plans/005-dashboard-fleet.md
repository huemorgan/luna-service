# Phase 005 — Dashboard & Agent Fleet Management

## Goal

Replace the auto-provisioning flow with a proper dashboard. Users sign in with Google, land on a dashboard showing their agents (initially empty), and explicitly create agents via a "New Agent" button. Fly.io provisioning errors surface clearly in the UI instead of silently failing.

**Render.com = management surface. Fly.io = agent runtime.**

## What Changes

### Current flow (broken)
```
Google sign-in → auto-create Fly Machine → redirect to /{slug}
```

### New flow
```
Google sign-in → redirect to /dashboard → user sees agent list (empty) → clicks "New Agent" → Fly Machine provisions → status updates live → user clicks agent to open it
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  DASHBOARD  (Render — React SPA)                        │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Agents   │  │ Team     │  │ Settings │  (future tabs)│
│  │ (active) │  │ Members  │  │ Billing  │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│                                                         │
│  Agent List:                                            │
│  ┌─────────────────────────────────────────────┐       │
│  │ 🟢 Marketing Luna   running   $4.20/mo      │ →open │
│  │ 🔴 Dev Agent        error     —              │ →retry│
│  │ ⚪ Research Bot     stopped   $0.00          │ →start│
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  [+ New Agent]                                          │
└─────────────────────────────────────────────────────────┘
         │
         │ API calls
         ▼
┌─────────────────────────────────────────────────────────┐
│  CONTROL PLANE API  (Render — FastAPI)                  │
│                                                         │
│  POST /api/agents          → create agent + provision   │
│  GET  /api/agents          → list agents                │
│  GET  /api/agents/:id      → agent detail               │
│  POST /api/agents/:id/stop → stop Fly Machine           │
│  POST /api/agents/:id/start → start Fly Machine         │
│  DELETE /api/agents/:id    → destroy agent              │
│  POST /api/agents/:id/retry → retry failed provisioning │
│                                                         │
│  GET  /api/account         → account info               │
│  GET  /api/account/members → team members (future)      │
└─────────────────────────────────────────────────────────┘
         │
         │ Fly Machines API
         ▼
┌─────────────────────────────────────────────────────────┐
│  FLY.IO  — Agent Runtime                                │
│  Each agent = one Fly Machine                           │
│  Each machine = unmodified Luna Docker image            │
└─────────────────────────────────────────────────────────┘
```

## Implementation Steps

### Step 1: Remove auto-provisioning from auth

**File:** `cloud/api/auth_routes.py`

- Remove the `asyncio.create_task(provision_luna_for_account(...))` call from `google_callback`
- Change redirect from `/{account.slug}` to `/dashboard`
- Auth callback only creates user + account records, nothing else

### Step 2: Build agent CRUD API

**File:** `cloud/api/agent_routes.py` (rewrite)

Endpoints:

| Method | Path | Action |
|--------|------|--------|
| `GET` | `/api/agents` | List all agents for the authenticated account |
| `POST` | `/api/agents` | Create a new agent — starts Fly provisioning in background |
| `GET` | `/api/agents/{id}` | Get single agent detail (status, config, URL) |
| `POST` | `/api/agents/{id}/start` | Start a stopped agent |
| `POST` | `/api/agents/{id}/stop` | Stop a running agent |
| `POST` | `/api/agents/{id}/retry` | Retry a failed provisioning |
| `DELETE` | `/api/agents/{id}` | Destroy agent (Fly Machine + DB schema) |

The `POST /api/agents` endpoint:
1. Creates `Agent` record with `status=provisioning`
2. Launches `provision_luna_for_account()` as a background task
3. Returns immediately with the agent ID and status
4. Frontend polls `GET /api/agents/{id}` for status updates

Error handling:
- Fly API unreachable → agent status = `error`, error message stored in `Agent.error_message`
- Machine created but crashes → agent status = `error`, Fly events fetched for diagnostics
- DB schema creation fails → agent status = `error`, cleanup attempted

### Step 3: Add error tracking to Agent model

**File:** `cloud/db/models.py`

Add to `Agent`:
- `error_message: str | None` — human-readable last error
- `error_at: datetime | None` — when the error occurred

### Step 4: Update provisioning workflow

**File:** `cloud/provisioning/workflow.py`

- Store error details in `agent.error_message` on failure
- Add `deprovision_agent()` function to tear down Fly Machine + archive DB schema
- Make provisioning fully idempotent (retry-safe)

### Step 5: Build Dashboard UI

**File:** `cloud/ui/src/pages/Dashboard.tsx` (rewrite)

Layout:
```
┌─ Header ─────────────────────────────────────────────┐
│ 🌙 Luna Service    Account: Roy's Workspace    [▾]   │
│                                          Sign out    │
├──────────────────────────────────────────────────────┤
│                                                      │
│  My Agents                          [+ New Agent]    │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ (empty state)                                  │  │
│  │                                                │  │
│  │  🌙  No agents yet                             │  │
│  │                                                │  │
│  │  Create your first Luna agent to get started.  │  │
│  │                                                │  │
│  │  [+ Create Agent]                              │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  — or when agents exist: ─────────────────────────   │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ 🟢 My Luna           running    2h ago       │    │
│  │    luna.com.ai/vaselin                [Open]  │    │
│  ├──────────────────────────────────────────────┤    │
│  │ 🔴 Dev Bot            error                  │    │
│  │    Failed: Fly Machine crashed       [Retry]  │    │
│  ├──────────────────────────────────────────────┤    │
│  │ ⚪ Research            stopped                │    │
│  │                               [Start] [Delete]│    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
└──────────────────────────────────────────────────────┘
```

States:
- **Empty**: no agents → show empty state with CTA
- **Provisioning**: agent being created → show spinner + "Setting up..."
- **Running**: agent live → show "Open" button linking to `/{slug}`
- **Error**: provisioning failed → show error message + "Retry" button
- **Stopped**: agent paused → show "Start" and "Delete" buttons

### Step 6: Create Agent dialog

When user clicks "New Agent":
1. Modal/dialog asks for agent name (default: "My Luna")
2. Submit → `POST /api/agents` → dialog shows provisioning progress
3. Poll status every 2s until `running` or `error`
4. On success → agent appears in list with "Open" link
5. On error → agent appears with error message and "Retry"

### Step 7: Wire proxy to handle multi-agent routing

**File:** `cloud/api/proxy.py`

Currently the proxy routes `/{account_slug}/...` to a single agent. With multiple agents per account, we need:
- Keep `/{slug}/` as the default agent route (first or primary agent)
- Add `/{slug}/agents/{agent_name}/` for routing to specific agents (future)
- For now, the proxy just picks the first running agent for the account slug

## Testing

### Manual test flow
1. Visit luna.com.ai → see landing page
2. Sign in with Google → redirected to /dashboard
3. See empty agent area
4. Click "New Agent" → enter name → see provisioning state
5. Agent transitions to running → click Open → see Luna chat
6. Return to dashboard → see agent listed as running
7. Stop agent from dashboard → status changes to stopped
8. Start agent → status changes to running
9. Delete agent → removed from list

### Error test
1. Break Fly credentials intentionally
2. Try creating agent
3. See clear error message in dashboard
4. Fix credentials, click Retry
5. Agent provisions successfully

## Files Changed

| File | Change |
|------|--------|
| `cloud/api/auth_routes.py` | Remove auto-provision, redirect to /dashboard |
| `cloud/api/agent_routes.py` | Full CRUD API for agents |
| `cloud/db/models.py` | Add error_message, error_at to Agent |
| `cloud/provisioning/workflow.py` | Error storage, deprovision, retry support |
| `cloud/ui/src/pages/Dashboard.tsx` | Full dashboard rewrite |
| `cloud/ui/src/App.tsx` | Update routing |
| `cloud/main.py` | Ensure /dashboard serves SPA |

## Not in This Phase

- Team invitations and member management (data model exists, UI deferred)
- Billing / cost display (Stripe integration is separate phase)
- Agent marketplace / templates
- Per-agent configuration UI (plugins, model selection)
- Bulk operations
- Activity audit log
