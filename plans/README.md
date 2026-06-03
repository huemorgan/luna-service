# Luna Service — MVP Plans

## What "MVP" Means Here

The MVP delivers exactly this experience:

1. A user visits `luna.com.ai`
2. Clicks "Sign in with Google"
3. Authenticates with Google (Novalystrix OAuth app)
4. Is redirected to `luna.com.ai/{their-account-slug}` within ~60 seconds
5. Sees their own private Luna chat interface
6. Has a real, multi-turn conversation with their Luna
7. Comes back tomorrow → same URL, same Luna, remembers them

**Out of scope for MVP:**
- Multi-user accounts (teams/invites)
- Billing / paid tiers
- Always-on Lunas / triggers
- File uploads
- MCP server management UI
- Mobile native app
- Subdomain routing (path-based only)
- Email/password auth (Google OAuth only)

## Phase Structure

Four phases. Each phase is shippable on its own — each ends with something testable that delivers visible value.

| # | Phase | What Ships | Hosting |
|---|-------|-----------|---------|
| **001** | **Luna Hosted Mode** | Luna OSS modified to accept trusted-proxy auth instead of its own login. Hosted Docker image built. | Local Docker |
| **002** | **Control Plane Skeleton** | FastAPI control plane with Google OAuth, Postgres-backed accounts, login/logout/dashboard UI. No Luna integration yet. | Local + Render Postgres |
| **003** | **Local Provisioning + Routing** | Control plane spins up per-user Luna Docker containers and proxies requests to them. **Full MVP works on a single laptop.** | Local Docker |
| **004** | **Fly + Render Deployment** | Swap local Docker for Fly Machines. Deploy control plane to Render. Production live at `luna.com.ai`. | Production |

## Why This Order

- **001 first** because every other phase depends on Luna being able to run in hosted (no-self-auth) mode. This is the *only* phase that touches Luna OSS code — and the change is small and generally useful.
- **002 second** because the control plane is a normal web app and can be built/tested without any Luna infrastructure complexity.
- **003 third** because gluing the two together (control plane + Luna fleet) is a meaty integration that benefits from being done locally first, where iteration is fast and free.
- **004 last** because production deployment is mechanical once 003 works locally — same code, swap the runtime adapter from Docker-local to Fly-API.

## Dev Process

Every phase follows `skills/devprocess/SKILL.md`:

1. Branch named after phase folder (e.g., `001-luna-hosted-mode`)
2. **Write E2E scenarios first** in `tests/XXX-name/` (LLM-driven, not coded assertions)
3. Implement the plan, phase by phase, committing as you go
4. Run the E2E scenarios in a browser, screenshot + DOM, judge pass/fail
5. Live walkthrough (real conversation with the deployed thing)
6. Report results in `dojo-results/NNNN-XXX-name/`

## Test Architecture

Tests are **dojo-style** (see `dojo-vision/vision.md`) — Markdown scenarios that the LLM executes in a browser, judging behavior qualitatively with screenshot/DOM evidence.

Two layers of tests exist in this repo:

| Layer | Where | What It Tests |
|-------|-------|--------------|
| **Luna agent dojo** | `luna/dojo/tests/` (inside submodule) | Does the agent behave correctly in conversations? |
| **Luna Service dojo** | `tests/` and `dojo-results/` (this repo) | Does the platform provision, route, and isolate correctly? |

When implementing a phase, write platform tests in `tests/XXX-name/`. Don't duplicate Luna's own tests — assume Luna works correctly inside its container.

## Accounts & Credentials Needed

See `../.env.example` for the canonical list of env vars and source pointers.

| Service | Status | Where to Get |
|---------|--------|--------------|
| Anthropic API key | ✓ Have it | `../luna/.env`, also set as `sync: false` on Render `runluna` |
| OpenAI API key | ✓ Have it | `../luna/.env`, also on Render `runluna` |
| Tavily API key (web search) | ✓ Have it | `../luna/.env`, also on Render `runluna` |
| Render account | ✓ Have it | New `luna-service` web service created, separate from old `runluna` |
| Cloudflare + `luna.com.ai` DNS | ✓ Zone exists | User will move domain to `luna-service.onrender.com` when ready |
| Google Cloud project + OAuth client | ⏳ To create | Inside `novalystrix.ai` Workspace org |
| Fly.io account | ⏳ User opening | Needed for phase 004 only |
| Render Postgres (tenant DB) | ⏳ To create | Same Render account — **second** Postgres instance (`luna-tenant-prod`), Standard plan, Oregon region, pgvector + HNSW enabled |
| Cloudflare R2 bucket | ⏳ To create | Under the existing Cloudflare account |

**Phases 001-003 can proceed with what we have today.** Phase 004 adds: Google OAuth, Fly, the second Render Postgres, R2.

### Render deployment strategy

New `luna-service` web service on Render — clean slate, separate from old `runluna`. User will move `luna.com.ai` domain to it when MVP is ready (phase 004). Old `runluna` stays untouched until then.

## Risks & Decisions Punted

Tracking these so we don't forget:

| Topic | MVP Decision | Defer To |
|-------|--------------|----------|
| Multi-tenancy in DB | Schema-per-tenant on a shared Render Postgres instance (one for control-plane data, one for tenant data) | Right approach for v1, no defer needed |
| Vault key derivation | Per-tenant derivation from a single root env var (no KMS yet) | Phase 5+ — add AWS KMS or equivalent |
| LLM cost metering | Track per-account but don't enforce caps yet | Post-MVP — needed before billing |
| Sleep / scale-to-zero | All Lunas always-on in MVP for simplicity | Phase 5+ — adds suspend/resume cycle |
| Subdomain routing | Path-based only (`luna.com.ai/alice`) | Post-MVP if user demand |
| Error handling polish | "Reasonable" — not designed-failure modes | Post-MVP polish phase |
| Mobile responsive | Desktop-first; mobile-functional but not optimized | Post-MVP |
| Billing / Stripe | Free tier only, no payment integration | Post-MVP — separate phase |
| Email notifications | None | Post-MVP |
| Admin / support dashboard | None | Post-MVP |

These are intentionally cut to keep MVP scope realistic. Re-visit after MVP ships and we know what users actually need.

## Definition of Done (MVP)

The MVP is complete when a non-developer can:

1. Visit `https://luna.com.ai` on a fresh device
2. Click "Sign in with Google" and complete OAuth
3. Wait at most 60 seconds while their Luna provisions
4. Land at `https://luna.com.ai/{their-slug}` and see a working Luna
5. Have a 5-turn conversation that demonstrates memory and personality
6. Close the browser, come back 24 hours later
7. Sign in again, land on the same URL, with their conversation history intact
8. Verify (via dojo test scenarios) that another user signing up does NOT see their data

When all of the above pass dojo tests in production, MVP ships.
