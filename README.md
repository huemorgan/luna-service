# Luna Service

The hosted multi-tenant platform for [Luna](https://github.com/huemorgan/luna). One signed-in user, one dedicated Luna instance, your data isolated from everyone else's.

**Status:** MVP planning phase. Implementation hasn't started yet.

## What This Repo Is

This repo is the **control plane and operations layer** that wraps the OSS Luna agent. It does NOT contain Luna itself — Luna lives as a Git submodule at `luna/`.

| Layer | Where |
|-------|-------|
| **The agent (OSS)** | `luna/` submodule, pulled from `huemorgan/luna` |
| **Control plane** | `cloud/` (to be built in plan 002) — FastAPI app, Google OAuth, account management, runtime provisioning, routing |
| **Vision + plans + tests** | `vision/`, `plans/`, `tests/`, `dojo-vision/` (this) |

## Where To Start

- **Product vision:** `vision/vision.md`
- **Filesystem architecture:** `vision/filesystem-architecture.md`
- **MVP plan overview:** `plans/README.md`
- **Implementation phases:** `plans/001-*/PLAN.md` through `plans/004-*/PLAN.md`
- **Test philosophy:** `dojo-vision/vision.md`
- **Dev process to follow:** `skills/devprocess/SKILL.md`

## The MVP, In One Sentence

A user visits `luna.com.ai`, signs in with Google, waits up to a minute, and then has their own private Luna at `luna.com.ai/<their-slug>` that remembers them, can't see anyone else's data, and keeps working tomorrow.

## Repo Layout

```
luna-service/
├── luna/                       # Git submodule — the OSS Luna agent (don't edit here)
├── cloud/                      # (to build) FastAPI control plane + React UI
├── dev/                        # (to build) local dev harnesses (docker-compose etc.)
│
├── vision/                     # Why we're building this, how it's shaped
│   ├── vision.md
│   └── filesystem-architecture.md
│
├── plans/                      # Implementation phases — read these in order
│   ├── README.md               # Phase overview + decisions
│   ├── 001-luna-hosted-mode/PLAN.md
│   ├── 002-control-plane-skeleton/PLAN.md
│   ├── 003-local-provisioning-and-routing/PLAN.md
│   └── 004-fly-deployment/PLAN.md
│
├── tests/                      # Dojo-style E2E scenarios per phase
│   ├── 001-luna-hosted-mode/
│   ├── 002-control-plane-skeleton/
│   ├── 003-local-provisioning-and-routing/
│   └── 004-fly-deployment/
│
├── dojo-vision/                # Testing philosophy
│   └── vision.md
│
├── dojo-results/               # (populated as plans execute) numbered run results
│
└── skills/                     # LLM skills (copied from .cursor/skills)
    └── devprocess/SKILL.md     # The dev process to follow for each plan
```

## How To Work On This

When you (the LLM in Cursor) are asked to execute a plan, follow `skills/devprocess/SKILL.md`:

1. Branch named after the plan folder (e.g., `001-luna-hosted-mode`)
2. **Write the test scenarios first** in `tests/XXX-name/` (most already drafted — refine as needed)
3. Implement the plan, phase by phase
4. Run scenarios in a real browser (you are the test framework — open the browser, screenshot, judge pass/fail)
5. Do the live walkthrough (a real multi-turn conversation, judged qualitatively)
6. Write results to `dojo-results/NNNN-XXX-name/`

## Accounts & Secrets

See `.env.example` for the full list of env vars and where to source each one.

What we already have (reusable from prior projects):

- **LLM keys:** Anthropic, OpenAI, Tavily in `../luna/.env` and `../luna-dojo/luna/.env`
- **Render account:** new `luna-service` web service created, separate from old `runluna`
  - LLM keys: copy from existing `runluna` service dashboard
- **Cloudflare:** `luna.com.ai` zone exists. User will move the domain to point at `luna-service.onrender.com` when ready.
- **Domain:** `luna.com.ai` registered and pointed at Cloudflare nameservers

What we still need to create:

- **Google OAuth client** inside `novalystrix.ai` Workspace (phase 002)
- **Second Render Postgres** for tenant DB (phase 004)
- **Fly.io account** + `luna-tenants-prod` app + API token (phase 004)
- **R2 bucket** + scoped API token under existing Cloudflare account (phase 004)

## Related Projects

- `../luna` — the OSS agent, this repo's main dependency
- `../luna-dojo` — the OSS agent's testing dojo (different layer from this repo's tests)

## Vision Documents

For the "why" behind every architectural choice in this repo, read in order:

1. `vision/vision.md` — product positioning, all-inclusive billing, Google auth, OSS-friendly architecture
2. `vision/filesystem-architecture.md` — why Postgres + R2 + Volumes (not just one)
3. `plans/README.md` — MVP scoping decisions and what was cut

If something in a plan or test doesn't match the vision, the vision is likely wrong, or the plan is wrong, or both — bring it up before implementing.
