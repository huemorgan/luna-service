# Phase 002 — Control Plane Skeleton

## Purpose

Build the control plane as a standalone web application. It handles user signup via Google OAuth, manages accounts in its own Postgres database, and exposes a dashboard UI. **No Luna integration yet** — that comes in phase 003.

End of phase: a real human can visit the local control plane, sign in with Google, see their account dashboard with a placeholder "Your Luna" panel that just shows "Not provisioned yet."

## Result

After this phase:
- Control plane runs locally at `http://localhost:8000`
- Google OAuth sign-in works against the Novalystrix Google Workspace OAuth app
- New users automatically get a single-member Account (themselves)
- Users can sign out and sign back in
- Dashboard shows their account name + a "Luna status: not provisioned" placeholder
- Postgres tables exist for `users`, `accounts`, `memberships`, `agents` (the registry — agent rows can be created but no actual Luna is spun up)
- Deployed to Render staging (`luna-service-control-staging.onrender.com`)

## Prerequisites

- Phase 001 complete (Luna hosted mode available) — but not required to consume yet
- Render account exists
- Google Cloud project created inside `novalystrix.ai` Workspace
- OAuth 2.0 Client ID created with redirect URIs:
  - `http://localhost:8000/auth/google/callback`
  - `https://luna-service-control-staging.onrender.com/auth/google/callback`
  - (Production callback added later in phase 004)

## Tasks

### 1. Project structure

Create `cloud/` directory at repo root:

```
cloud/
├── pyproject.toml             # FastAPI + SQLAlchemy + Authlib + ...
├── alembic.ini
├── alembic/                   # Migrations for control-plane DB
├── main.py                    # FastAPI app entry
├── config.py                  # Pydantic settings
├── db/
│   ├── __init__.py
│   ├── models.py              # User, Account, Membership, Agent
│   ├── session.py             # SQLAlchemy session factory
│   └── seed.py                # Dev seed data
├── auth/
│   ├── __init__.py
│   ├── google.py              # Google OAuth flow
│   ├── session.py             # Session cookie handling
│   ├── identity.py            # IdentityProvider Protocol (allows stub)
│   └── deps.py                # FastAPI dependencies (require_user, etc.)
├── api/
│   ├── __init__.py
│   ├── auth_routes.py         # /auth/login, /auth/callback, /auth/logout
│   ├── account_routes.py      # /api/accounts/me
│   └── agent_routes.py        # /api/agents (list/get — no provision yet)
├── ui/
│   ├── (Vite + React + Tailwind app)
│   ├── package.json
│   └── src/
│       ├── App.tsx
│       ├── pages/
│       │   ├── Landing.tsx
│       │   ├── Login.tsx
│       │   ├── Dashboard.tsx
│       │   └── AcceptInvite.tsx  (placeholder)
│       └── ...
└── tests/                     # Coded tests for cloud/ only (units/integration)
```

### 2. Dependencies

`cloud/pyproject.toml`:
- `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`
- `sqlalchemy[asyncio]`, `asyncpg`, `alembic`
- `authlib`, `itsdangerous`, `httpx`
- `python-multipart`, `redis` (for session storage later, optional for MVP)

`cloud/ui/package.json`:
- React 19, Vite 7, TailwindCSS 4, lucide-react, react-router-dom

### 3. Data model

Migrations in `cloud/alembic/versions/`:

```sql
-- 001_initial.sql

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  google_sub TEXT UNIQUE NOT NULL,
  email TEXT NOT NULL,
  name TEXT,
  avatar_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_login_at TIMESTAMPTZ
);

CREATE TABLE accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,           -- used in URL: luna.com.ai/{slug}
  name TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'free',   -- free | pro | power | enterprise
  status TEXT NOT NULL DEFAULT 'active', -- active | suspended | deleted
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'owner',  -- owner | admin | member
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(account_id, user_id)
);

CREATE TABLE agents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  creator_id UUID NOT NULL REFERENCES users(id),
  name TEXT NOT NULL DEFAULT 'My Luna',
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | provisioning | running | sleeping | error | deleted
  runtime_kind TEXT,                        -- 'docker-local' | 'fly-machine'
  runtime_ref TEXT,                         -- container name OR fly machine id
  internal_url TEXT,                        -- where the proxy forwards to
  db_schema TEXT,                           -- name of this Luna's Postgres schema
  vault_key_ref TEXT,                       -- reference, not the key itself
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_active_at TIMESTAMPTZ
);

CREATE TABLE audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID REFERENCES accounts(id),
  actor_user_id UUID REFERENCES users(id),
  action TEXT NOT NULL,
  target TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4. Identity provider abstraction

`cloud/auth/identity.py`:

```python
class IdentityProvider(Protocol):
    async def get_authorization_url(self, state: str) -> str: ...
    async def exchange_code(self, code: str) -> "UserInfo": ...

class GoogleIdentityProvider:  # real implementation
    ...

class StubIdentityProvider:  # for dev/test
    """Returns hardcoded test users from a config. Skips real OAuth."""
    ...
```

Switched via `CLOUD_IDENTITY_PROVIDER` env var (`google` | `stub`).

### 5. Google OAuth implementation

`cloud/auth/google.py`:

- `/auth/login` — redirects to Google authorization URL with state token
- `/auth/google/callback` — receives code, exchanges for `id_token`, verifies:
  - Signature (Google JWKS)
  - `aud` matches our client ID
  - `iss` is `https://accounts.google.com`
  - `email_verified` is true
- Upserts `User` by `google_sub`
- If no `Membership` exists, creates an `Account` (slug from email username, dedup if collision) with the user as owner
- Sets session cookie (HttpOnly, Secure, SameSite=Lax)
- Redirects to `/dashboard`

`/auth/logout` — clears session cookie, redirects to landing.

### 6. Session middleware

- `itsdangerous` signed session cookie containing `{user_id, active_account_id}`
- `cloud/auth/deps.py`:
  - `require_user(request)` → returns User or 401
  - `require_active_account(request)` → returns (User, Account) or 401/403

### 7. API routes (minimal)

- `GET /api/auth/me` — current user info + active account (or 401)
- `GET /api/accounts/me` — active account details
- `GET /api/agents` — list of agents in active account (will be empty until phase 003)
- `POST /api/agents` — placeholder (returns 501 Not Implemented in phase 002)
- `GET /api/auth/mode` — returns `"google" | "stub"` so UI knows what login button to show

### 8. UI

- **Landing page** (`/`) — minimal: Luna branding, "Sign in with Google" button → `/auth/login`
- **Dashboard** (`/dashboard`) — after login:
  - Show user's name + avatar (top right)
  - Show account name + slug
  - Big card: "Your Luna" with status placeholder ("Not provisioned yet — coming in phase 003")
  - Sign out button
- **Login redirect** (`/login`) — just redirects to `/auth/login` (handy URL for users to bookmark)
- Use TailwindCSS + minimal styling matching Luna's design language (dark "ink" theme, moon accent)

### 9. Local dev workflow

`Makefile` (extend the root one or create `cloud/Makefile`):
- `make cloud-up` — start Postgres for control plane, run migrations, start FastAPI + Vite dev
- `make cloud-stub-login` — seed stub identity user, generate test session, open browser at `/dashboard`
- `make cloud-test` — run coded tests
- `make cloud-dojo` — run dojo scenarios (LLM-driven, manual for now)

### 10. Deploy to Render

The user has created a new `luna-service` web service on Render, pointing at the `huemorgan/luna-service` repo. Domain `luna.com.ai` will be moved to point at it when ready (phase 004).

- `cloud/render.yaml`:
  - Web: Docker, Standard plan, Oregon, Dockerfile `./cloud/Dockerfile`
  - Postgres: new `luna-service-cp` instance (Starter or Standard, Oregon, PG 16)
- Environment vars (set in Render dashboard, NOT in render.yaml):
  - `CLOUD_ENV=staging`
  - `CLOUD_IDENTITY_PROVIDER=stub` (initially — switch to `google` once OAuth app exists)
  - `CLOUD_SESSION_SECRET` (use `generateValue: true`)
  - `CLOUD_DATABASE_URL` (from `fromDatabase`)
  - LLM keys: copy from existing `runluna` service dashboard → `LUNA_ANTHROPIC_API_KEY`, `LUNA_OPENAI_API_KEY`, `LUNA_TAVILY_API_KEY`
- Push to `main` → Render auto-deploys → smoke test at `luna-service.onrender.com`

## Tests

Write **before** implementation in `tests/002-control-plane-skeleton/`. Scenarios cover Google login, stub login, session persistence, sign out, multi-tab behavior, etc.

## Definition of Done

- [ ] Local control plane starts cleanly with `make cloud-up`
- [ ] Stub identity provider lets you "log in" as a fake user for fast dev iteration
- [ ] Real Google OAuth works against the Novalystrix OAuth app (when env vars are set)
- [ ] New user → Account + Membership + User rows created atomically
- [ ] Returning user → reuses existing rows, updates `last_login_at`
- [ ] Sign out clears session, returning to landing
- [ ] Dashboard shows account info and the "Luna not provisioned" placeholder
- [ ] All dojo scenarios in `tests/002-control-plane-skeleton/` pass
- [ ] Deployed to Render staging, smoke-tested in browser
- [ ] Result summary in `dojo-results/0002-002-control-plane-skeleton/summary.md`
