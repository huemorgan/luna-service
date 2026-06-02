# Phase 003 — Local Provisioning + Routing

## Purpose

Glue Phase 001 (Luna in hosted mode) and Phase 002 (control plane) together. The control plane now **provisions a Luna instance per user on signup** (as a local Docker container) and **routes their requests** to their Luna at `localhost:8000/{their-slug}`.

End of phase: the **full MVP works end-to-end on a single laptop**. Sign in with Google → control plane provisions a Luna container → you're redirected to `/your-slug` → chat with your Luna → conversation persists across sign-outs → another user signing up gets a completely separate Luna with separate data.

## Result

After this phase:
- On user signup, control plane atomically:
  1. Creates a Postgres schema for their Luna (`luna_user_<slug>`)
  2. Generates a per-tenant vault key
  3. Spawns a Luna Docker container with all env vars set (DB URL with schema, vault key, trusted-proxy secret)
  4. Waits for the container to be healthy
  5. Records `agent_id`, `runtime_ref` (container name), `internal_url` (`http://luna-<slug>:8000`)
- Control plane proxies `/{account_slug}/*` to that account's Luna container, injecting `X-Luna-User` and `X-Luna-Proxy-Secret` headers
- SSE streams pass through cleanly
- Two users on the same laptop = two Luna containers, two schemas, two vault keys, zero data crossover
- Provisioning time: target < 30 seconds on a developer laptop (cold image already pulled)

## Prerequisites

- Phase 001 done — `luna-hosted:dev-001` image available
- Phase 002 done — control plane running locally
- Both work independently (verified by their respective dojo tests)

## Tasks

### 1. Runtime provider abstraction

`cloud/runtime/`:

```python
# cloud/runtime/base.py
class LunaRuntime(Protocol):
    async def provision(self, spec: AgentSpec) -> RuntimeHandle: ...
    async def get_status(self, handle: RuntimeHandle) -> RuntimeStatus: ...
    async def wake(self, handle: RuntimeHandle) -> None: ...
    async def stop(self, handle: RuntimeHandle) -> None: ...
    async def destroy(self, handle: RuntimeHandle) -> None: ...
    async def get_internal_url(self, handle: RuntimeHandle) -> str: ...

class AgentSpec(BaseModel):
    account_slug: str
    db_schema: str
    db_url: str
    vault_key: bytes
    trusted_proxy_secret: str
    llm_provider_keys: dict[str, str]  # we provide these for MVP
    image_tag: str = "luna-hosted:dev-001"
```

Two implementations:

- `cloud/runtime/docker_local.py` — `DockerLocalRuntime` (this phase)
  - Uses Docker SDK / `docker` CLI to start a container
  - Container name: `luna-<slug>`
  - Network: shared Docker network with control plane and Postgres
  - Health check: poll `http://luna-<slug>:8000/healthz` until 200
- `cloud/runtime/fly_machines.py` — `FlyMachinesRuntime` (phase 004 stubs this; phase 004 implements)

Switched via `CLOUD_RUNTIME=docker-local | fly-machines`.

### 2. Tenant database provisioning

`cloud/db/tenant_provisioner.py`:

```python
async def provision_tenant_schema(
    shared_db_url: str,
    schema_name: str,
) -> tuple[str, str]:
    """
    Creates a Postgres schema and a scoped role for a new Luna tenant.
    Returns (db_url_for_luna, role_password) — the role can ONLY access this schema.
    """
    # 1. CREATE SCHEMA luna_user_<slug>
    # 2. CREATE ROLE luna_user_<slug>_role LOGIN PASSWORD '<random>'
    # 3. GRANT ALL ON SCHEMA luna_user_<slug> TO luna_user_<slug>_role
    # 4. ALTER ROLE luna_user_<slug>_role SET search_path = luna_user_<slug>
    # 5. REVOKE ALL ON SCHEMA public FROM luna_user_<slug>_role
    # 6. Return connection URL with the new credentials + search_path option
```

`async def destroy_tenant_schema(schema_name)` for cleanup tests.

### 3. Per-tenant vault key generation

`cloud/vault/keygen.py`:

```python
def derive_tenant_vault_key(
    root_key: bytes,    # CLOUD_VAULT_ROOT_KEY env var
    tenant_id: str,     # account UUID as string
) -> bytes:
    # HKDF-SHA256 derivation
    # Returns 32 bytes
```

For MVP, `CLOUD_VAULT_ROOT_KEY` is just an env var (high-entropy random). Post-MVP swaps to KMS.

### 4. Provisioning workflow

`cloud/provisioning/workflow.py`:

```python
async def provision_luna_for_account(account: Account) -> Agent:
    """
    Idempotent. Safe to call again if a previous attempt partially failed.
    """
    # 1. Find or create Agent row in 'provisioning' state
    # 2. If schema doesn't exist: create it (idempotent)
    # 3. Derive vault key (deterministic from account_id)
    # 4. Generate trusted_proxy_secret if missing
    # 5. Provision runtime (Docker container OR Fly Machine)
    # 6. Wait for health check (max 60s)
    # 7. Update Agent: status='running', runtime_ref, internal_url
    # 8. Audit log entry
    # 9. Return Agent
```

Failure handling:
- Each step is its own try/except → mark Agent `status='error'`, store error details
- On retry, skip steps already completed (idempotent)

### 5. Trigger provisioning on signup

In `cloud/auth/google.py` (or the user-creation flow):
- After creating Account for new user → kick off `provision_luna_for_account` as a background task
- Don't block the OAuth callback on provisioning (would make signup slow)
- Redirect user to `/{account_slug}` immediately — that page will poll until Luna is ready

### 6. Provisioning status page

`cloud/ui/src/pages/Provisioning.tsx`:
- When user lands on `/{slug}` and their Agent is in `pending` or `provisioning` state
- Show a friendly "Setting up your Luna..." screen with spinner
- Poll `/api/agents/me/status` every 2 seconds
- When status flips to `running`, transition to the chat UI

### 7. Routing / reverse proxy

`cloud/api/proxy.py`:

```python
@router.api_route("/{account_slug}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_luna(request, account_slug, path):
    # 1. Resolve session → user
    # 2. Check user has membership in account_slug
    # 3. Lookup agent for that account (must be 'running')
    # 4. Strip /{account_slug} prefix from path
    # 5. Build URL: f"{agent.internal_url}/{path}"
    # 6. Forward request with:
    #    - All original headers EXCEPT cookies (don't leak session to Luna)
    #    - Add X-Luna-User: user.email
    #    - Add X-Luna-Account: account.slug
    #    - Add X-Luna-Proxy-Secret: <secret from env>
    # 7. Stream response back (SSE-compatible)
    # 8. Update agent.last_active_at
```

Use `httpx.AsyncClient` with streaming, or `starlette.responses.StreamingResponse`.

Special case: `GET /{slug}` with no further path → serve a wrapper page that loads Luna's UI in an iframe pointing to `/{slug}/` (the trailing slash routes to Luna's UI).

OR: serve Luna's UI assets directly (proxied). Choose iframe for MVP — simpler.

### 8. Docker compose for full local stack

`docker-compose.local.yml` at repo root:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    # Used as both control-plane DB and tenant DB (different databases inside)
  redis:
    image: redis:7-alpine
  control-plane:
    build: ./cloud
    depends_on: [postgres, redis]
    ports: ["8000:8000"]
    environment:
      CLOUD_RUNTIME: docker-local
      CLOUD_DATABASE_URL: postgresql://...
      CLOUD_TENANT_DATABASE_URL: postgresql://...  # different DB on same Postgres for tenants
      CLOUD_TRUSTED_PROXY_SECRET: <generated>
      CLOUD_VAULT_ROOT_KEY: <generated>
      LUNA_ANTHROPIC_API_KEY: <from .env>
      ...
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # so control plane can spawn Lunas
```

(In production we use Fly's API instead of Docker socket, abstracted behind the runtime provider.)

### 9. End-to-end smoke

`make e2e-local`:
1. Bring up the stack fresh
2. Use control plane's stub identity to "sign in" as User A
3. Wait for Agent A to provision
4. Open chat, send a message, verify response
5. Sign out
6. Stub-sign in as User B (different identity)
7. Wait for Agent B to provision
8. Verify two Luna containers running, two schemas in Postgres, different vault keys
9. Sign User B out, sign User A back in, verify their original conversation history is still there

## Tests

Write **before** implementation in `tests/003-local-provisioning-and-routing/`. Multi-user scenarios are first-class — the key thing to verify is isolation.

## Definition of Done

- [ ] Control plane can spawn a Luna container via Docker SDK
- [ ] Tenant schema creation works and is idempotent
- [ ] Vault key derivation is deterministic per account
- [ ] Provisioning completes within 30 seconds on a dev laptop (image already pulled)
- [ ] Provisioning errors set Agent status to `error` with diagnostic info
- [ ] Routing proxy forwards all HTTP methods including SSE
- [ ] Multi-user isolation verified by dojo test (two stub users, no data crossover)
- [ ] Provisioning status page polls correctly and transitions
- [ ] All dojo scenarios in `tests/003-local-provisioning-and-routing/` pass
- [ ] Live walkthrough: real Google sign-in (local) → Luna provisions → 10-turn conversation → sign out → sign back in → conversation persists
- [ ] Result summary in `dojo-results/0003-003-local-provisioning-and-routing/summary.md`
