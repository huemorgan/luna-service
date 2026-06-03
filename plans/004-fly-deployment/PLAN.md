# Phase 004 — Fly + Render Production Deployment

## Purpose

Swap the local Docker runtime for **Fly Machines**, deploy the control plane to **Render**, and put **`luna.com.ai`** in front. End: a real user from anywhere can sign up at `luna.com.ai` and get their own Luna running on Fly's global infrastructure.

This phase is mostly **infrastructure plumbing** — no new logic. The runtime provider abstraction from phase 003 means swapping `DockerLocalRuntime` for `FlyMachinesRuntime` is a code change in one place; everything else stays the same.

## Result

After this phase:
- `https://luna.com.ai` is live with the marketing landing + Google sign-in (user moves domain from `runluna` to the new `luna-service` Render service)
- Control plane runs on Render as the **`luna-service`** web service (new, separate from old `runluna`)
- Control plane's Postgres on a new Render Postgres instance
- Tenant Postgres (Luna data) on a **second Render Postgres instance** (Standard, Oregon) — schema-per-tenant, pgvector + HNSW enabled
- Luna fleet on Fly Machines (`sjc` region — West Coast, matching Render Oregon for low DB latency, ~20ms hop)
- R2 bucket exists for future file storage (not used in MVP but provisioned)
- DNS, TLS, monitoring all wired
- A user can sign up, get a real Luna in < 60s, and chat

## Prerequisites

- Phase 003 complete and locally verified
- Phase 002 staging deployment running on the new `luna-service` Render service
- Fly.io account created (user is opening this)
- Render: new `luna-service` web service already created (phase 002), plus a new Postgres for tenant data
- Cloudflare: user will point `luna.com.ai` to the new `luna-service.onrender.com` (domain move from old `runluna`)
- Google OAuth app's production redirect URI added: `https://luna.com.ai/auth/google/callback`

## Tasks

### 1. Cloudflare — point domain to new service, add R2

- [ ] Log into Cloudflare, navigate to the `luna.com.ai` zone
- [ ] Update DNS: change the CNAME/A record from `runluna.onrender.com` → `luna-service.onrender.com`
- [ ] Verify proxy mode (orange cloud) is enabled
- [ ] Verify TLS mode is "Full (strict)"
- [ ] (Optional, post-MVP) Add wildcard `*.luna.com.ai` placeholder for future subdomain routing
- [ ] Create R2 bucket: `luna-service-prod`
- [ ] Create scoped R2 API token (read+write to `luna-service-prod` only) → save to Render env vars

### 2. Tenant Postgres on Render

We're using Render for both control-plane data and tenant data. Two separate Postgres instances on the same Render account — same dashboard, same bill, same backup story, same support relationship.

**Decision: what to do with the existing `luna-db`** (the existing Render Postgres has personal Luna data from the prior `runluna` deployment):

- **Option A (clean slate, recommended):** Rename `luna-db` → `luna-service-control` (or destroy + recreate); it becomes the control-plane DB for luna-service. The previous personal Luna data is wiped. **Before doing this, take a final dump and store it somewhere** (`pg_dump` → save to local disk + R2 bucket). Devprocess rule: data preservation is non-negotiable even for personal data.
- **Option B (preserve personal Luna):** Leave `luna-db` alone. Create a third Postgres `luna-service-control` for the new control plane. The old data stays accessible (and the old Luna is just one tenant in the new system if you want — by importing it later).

User decision needed — flagged in the README. **Default assumption: Option A** since user said "reset that project."

- [ ] In the Render dashboard, create a **second** Postgres instance named `luna-tenant-prod`
  - Plan: **Standard** ($20/mo — 1 GB RAM, 16 GB storage, daily backups + PITR)
  - Postgres version: **16** (latest pgvector + HNSW support)
  - Region: **Oregon** (match existing infra and Fly `sjc` for low query latency)
- [ ] Connect with `psql` and enable pgvector:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```
  (This is the *same* extension Luna's memory plugin already uses — see `luna/plugins/plugin_memory/__init__.py`, which builds an HNSW index on 1536-dim embeddings with cosine distance.)
- [ ] Verify HNSW works:
  ```sql
  CREATE TABLE _test_hnsw (id int, e vector(3));
  INSERT INTO _test_hnsw VALUES (1, '[1,2,3]'), (2, '[4,5,6]');
  CREATE INDEX ON _test_hnsw USING hnsw (e vector_cosine_ops);
  DROP TABLE _test_hnsw;
  ```
- [ ] Tune `maintenance_work_mem` to ~512MB (Render UI or `ALTER SYSTEM`) so per-tenant HNSW index builds aren't disk-bound
- [ ] Get the connection string from Render dashboard → this becomes `CLOUD_TENANT_DATABASE_URL`
- [ ] Document the **admin role** credentials (control plane uses these to `CREATE SCHEMA` and `CREATE ROLE` for new tenants)
- [ ] Backups: Render Standard plan does daily snapshots + 7-day PITR automatically. Verify in Render dashboard.

### 3. Render control plane — production config for `luna-service`

The `luna-service` Render web service was created in phase 002. Now we configure it for production.

- [ ] In Render dashboard, verify `luna-service` service settings:
  - Repo: `huemorgan/luna-service`, branch: `main`
  - Dockerfile: `./cloud/Dockerfile`
  - Plan: **Standard** (1GB RAM)
  - Region: **Oregon**
  - Health check: `/healthz`
- [ ] Add custom domain `luna.com.ai` in Render dashboard (after Cloudflare DNS updated in task 1)
- [ ] Create a new Render Postgres `luna-service-cp` for control-plane data (Standard, Oregon, PG 16)
- [ ] Environment variables (set via Render dashboard, not committed):
  - `CLOUD_ENV=production`
  - `CLOUD_RUNTIME=fly-machines`
  - `CLOUD_DATABASE_URL` (Render Postgres — control-plane data)
  - `CLOUD_TENANT_DATABASE_URL` (Render Postgres — admin connection for schema/role creation)
  - `CLOUD_TENANT_DB_HOST` (Render Postgres — hostname only, passed into Luna machines so they build per-tenant connection strings)
  - `CLOUD_SESSION_SECRET`
  - `CLOUD_VAULT_ROOT_KEY`
  - `CLOUD_TRUSTED_PROXY_SECRET`
  - `CLOUD_IDENTITY_PROVIDER=google`
  - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
  - `FLY_API_TOKEN` (read+write for the Luna app)
  - `FLY_APP_NAME=luna-tenants-prod` (the Fly app that holds all Luna Machines)
  - `LUNA_ANTHROPIC_API_KEY`, `LUNA_OPENAI_API_KEY`, `LUNA_TAVILY_API_KEY` (passed through to provisioned Lunas)
  - `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`
- [ ] Deploy → smoke test landing page at `https://luna.com.ai`

### 4. Fly setup

- [ ] Install Fly CLI locally, `fly auth login`
- [ ] Create Fly organization (or use personal)
- [ ] Create Fly **app** `luna-tenants-prod` (this app will hold all per-tenant Machines)
  ```bash
  fly apps create luna-tenants-prod
  ```
- [ ] Push the `luna-hosted` image to Fly's registry:
  ```bash
  fly deploy --image luna-hosted:dev-001 --build-only --app luna-tenants-prod
  ```
- [ ] Verify image is accessible: `fly machines list --app luna-tenants-prod`
- [ ] Create API token with scope `app:luna-tenants-prod` → save to Render env vars
- [ ] **Region:** create the Fly app in `sjc` (San Jose) to match Render Oregon. Round-trip Render Oregon ↔ Fly SJC is ~20ms. If we ever migrate Render to Virginia, switch Fly to `iad` at the same time.

### 5. Implement `FlyMachinesRuntime`

`cloud/runtime/fly_machines.py`:

```python
class FlyMachinesRuntime(LunaRuntime):
    def __init__(self, api_token: str, app_name: str):
        self.api_token = api_token
        self.app_name = app_name
        self.client = httpx.AsyncClient(
            base_url=f"https://api.machines.dev/v1/apps/{app_name}",
            headers={"Authorization": f"Bearer {api_token}"},
        )

    async def provision(self, spec: AgentSpec) -> RuntimeHandle:
        # POST /machines with image, env, region
        response = await self.client.post("/machines", json={
            "name": f"luna-{spec.account_slug}",
            "region": "sjc",  # match Render Oregon
            "config": {
                "image": f"registry.fly.io/{self.app_name}:dev-001",
                "env": {
                    "LUNA_AUTH_MODE": "trusted_proxy",
                    "LUNA_TRUSTED_PROXY_SECRET": spec.trusted_proxy_secret,
                    "LUNA_DATABASE_URL": spec.db_url,
                    "LUNA_DB_SCHEMA": spec.db_schema,
                    "LUNA_VAULT_MASTER_KEY": spec.vault_key.hex(),
                    **spec.llm_provider_keys,
                },
                "guest": {
                    "cpu_kind": "shared",
                    "cpus": 1,
                    "memory_mb": 1024,
                },
                "services": [{
                    "ports": [{"port": 80, "handlers": ["http"]}, {"port": 443, "handlers": ["tls", "http"]}],
                    "protocol": "tcp",
                    "internal_port": 8000,
                }],
            },
        })
        machine_id = response.json()["id"]
        return RuntimeHandle(kind="fly-machine", ref=machine_id)

    async def get_internal_url(self, handle) -> str:
        # Fly's internal DNS: <machine_id>.vm.<app>.internal
        # OR use private app URL: <app>.flycast
        return f"http://{handle.ref}.vm.{self.app_name}.internal:8000"

    async def wake(self, handle):
        await self.client.post(f"/machines/{handle.ref}/start")

    async def stop(self, handle):
        await self.client.post(f"/machines/{handle.ref}/suspend")  # suspend not stop for fast wake

    async def destroy(self, handle):
        await self.client.delete(f"/machines/{handle.ref}?force=true")
```

### 6. Internal networking (Render ↔ Fly)

Two options:

**Option A: Fly Machines reachable from Render via Fly's public anycast (`<app>.fly.dev`)**
- Easier setup, no VPN
- Slightly slower (public internet hop)
- Each Luna gets a `<machine_id>.fly.dev` URL
- Concern: this exposes Lunas publicly → must rely on `X-Luna-Proxy-Secret` for auth

**Option B: Fly WireGuard / private network**
- Render → Fly via Tailscale-like private network
- Lunas are *not* publicly addressable
- Stronger security
- More setup

**MVP choice: Option A.** Faster to ship. The trusted-proxy secret + the fact that Luna requires `X-Luna-User` header (won't respond to anything else) provides reasonable security. Move to Option B post-MVP.

Internal URL format with Option A:
- `https://<machine_id>.vm.luna-tenants-prod.fly.dev` (auto-routes to the right Machine)

### 7. Provisioning timing

Fly cold-start a fresh Machine from image: ~5-10 seconds. Then Luna boot (Python + plugins + migrations): another ~5-15 seconds. Total: **15-25 seconds for first provision**, well within the 60-second target.

For subsequent waking of suspended Machines (post-MVP): ~300ms.

### 8. Production smoke + monitoring

- [ ] First production sign-up by you (real Google account)
- [ ] Verify Luna provisions within 60s
- [ ] Chat 5 turns, verify response quality
- [ ] Sign out, sign back in next day, verify continuity
- [ ] Set up basic monitoring:
  - Render's built-in (CPU/memory/req-time)
  - Fly's built-in (Machine status, resource usage)
  - Sentry for error tracking in control plane

### 9. Marketing landing (minimal)

The landing page in phase 002 was utilitarian. Polish it now:
- Hero: "Your own AI agent. In the cloud. In under a minute."
- One CTA: "Sign in with Google"
- Brief: what Luna does, what makes it different (open source, your data, plugin-extensible)
- Footer: link to OSS repo, status page, ToS, privacy

Not a marketing site overhaul — just enough that the first visitor doesn't think it's broken.

## Tests

Write **before** implementation in `tests/004-fly-deployment/`. Many scenarios are repeats of phase 003 tests, now run against production infrastructure. New scenarios cover:
- DNS / TLS correctness
- Multi-region routing (if applicable)
- Fly Machine lifecycle (provision/suspend/destroy)
- Production-only failure modes (Render restart, Fly Machine eviction)

## Definition of Done

- [ ] `https://luna.com.ai` returns the landing page over TLS
- [ ] Google OAuth completes against the production OAuth app
- [ ] A new user signs up, provisions a Luna on Fly, lands in their chat — all within 60s
- [ ] Their Luna conversation persists across sessions
- [ ] Two real users → two Fly Machines, two Render Postgres schemas, isolated
- [ ] Render and Fly billing dashboards show the expected resource usage
- [ ] All dojo scenarios in `tests/004-fly-deployment/` pass against production
- [ ] Live walkthrough: real signup from a phone you've never used → full conversation works
- [ ] Result summary in `dojo-results/0004-004-fly-deployment/summary.md`
- [ ] **MVP shipped.** 🌙
