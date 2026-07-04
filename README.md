# Luna Service

The hosted multi-tenant platform for [Luna](https://github.com/huemorgan/luna). One signed-in user, one dedicated Luna instance, your data isolated from everyone else's.

**Status:** MVP shipped and live — under active development. The plans in `plans/` (001–034 and counting) track the work; each folder is an executed or in-flight phase.

## What This Repo Is

This repo is the **control plane and operations layer** that wraps the OSS Luna agent. It does NOT contain Luna itself — Luna lives as a Git submodule at `luna/`.

| Layer | Where |
|-------|-------|
| **The agent (OSS)** | `luna/` submodule, pulled from `huemorgan/luna` |
| **Control plane** | `cloud/` — FastAPI app: Google OAuth, tenant provisioning on Fly.io machines, image baking/promotion, admin fleet dashboard, credential gateway + vault, model catalog, metering, Composio trigger relay |
| **Plugin marketplace** | `luna-marketplaces/` submodule — the marketplace service behind `marketplaces.com.ai` |
| **Marketing site** | `website/` — static site (index, features, pricing, security, open-source, for-providers, blog) |
| **Vision + plans + tests** | `vision/`, `plans/`, `tests/`, `dojo-vision/` |

## How It Works, In One Sentence

A user visits `luna.com.ai`, signs in with Google, waits up to a minute, and then has their own private Luna at `luna.com.ai/<their-slug>` that remembers them, can't see anyone else's data, and keeps working tomorrow.

Under the hood: the control plane runs on Render, each tenant gets a dedicated Fly.io machine baked from a versioned image (`docker/luna-hosted.Dockerfile`), tenant state lives in Postgres + R2, and plugin credentials are provisioned through the gateway/vault rather than baked into images.

## Repo Layout

```
luna-service/
├── luna/                       # Git submodule — the OSS Luna agent (don't edit here)
├── luna-marketplaces/          # Git submodule — plugin marketplace service
├── cloud/                      # FastAPI control plane
│   ├── api/                    #   routes: auth, agents, admin, gateway, plugin catalog, relay
│   ├── auth/                   #   Google OAuth
│   ├── provisioning/           #   Fly.io machine lifecycle, image bake/promote
│   ├── gateway/                #   credential gateway: keys, policy, metering, model registry
│   ├── vault/                  #   secret storage for plugin provisioning
│   ├── relay/                  #   Composio trigger relay
│   ├── db/ + alembic/          #   Postgres models + migrations
│   └── ui/                     #   admin dashboard (fleet, machines, images, audit log)
├── website/                    # Marketing site (luna.com.ai)
├── docker/                     # Tenant image (luna-hosted.Dockerfile)
├── dev/                        # Local dev harnesses, backfills, probes
│
├── vision/                     # Why we're building this, how it's shaped
├── plans/                      # Implementation phases — numbered, read in order
├── tests/                      # Dojo-style E2E scenarios per phase
├── dojo-results/               # Numbered run results from executed plans
└── skills/                     # LLM skills (devprocess, luna-submodule-changes)
```

## Where To Start

- **Product vision:** `vision/vision.md`
- **Filesystem architecture:** `vision/filesystem-architecture.md`
- **Plan overview + MVP scoping:** `plans/README.md`
- **Test philosophy:** `dojo-vision/vision.md`
- **Dev process to follow:** `skills/devprocess/SKILL.md`

## How To Work On This

When you (the LLM) are asked to execute a plan, follow `skills/devprocess/SKILL.md`:

1. Branch named after the plan folder (e.g., `034-plugin-forge`)
2. **Write the test scenarios first** in `tests/XXX-name/`
3. Implement the plan, phase by phase
4. Run scenarios in a real browser (you are the test framework — open the browser, screenshot, judge pass/fail)
5. Do the live walkthrough (a real multi-turn conversation, judged qualitatively)
6. Write results to `dojo-results/NNNN-XXX-name/`

Luna changes never happen here directly — see `skills/luna-submodule-changes/` for how submodule bumps flow in.

## Accounts & Secrets

See `.env.example` for the full list of env vars and where to source each one. In broad strokes:

- **Render** hosts the control plane (`render.yaml`) and Postgres
- **Fly.io** hosts tenant machines (`luna-tenants-prod`)
- **Cloudflare** fronts `luna.com.ai` and provides the R2 bucket
- **Google OAuth** (Novalystrix Workspace client) handles sign-in
- **LLM keys** are provisioned to tenants through the credential gateway, not baked into images

## Related Projects

- `../luna` — the OSS agent, this repo's main dependency
- `../plugins/*` — extracted Luna plugins, published to the marketplace
- `luna-marketplaces/` — the marketplace service they're published to

## Vision Documents

For the "why" behind every architectural choice in this repo, read in order:

1. `vision/vision.md` — product positioning, all-inclusive billing, Google auth, OSS-friendly architecture
2. `vision/filesystem-architecture.md` — why Postgres + R2 + Volumes (not just one)
3. `plans/README.md` — MVP scoping decisions and what was cut

If something in a plan or test doesn't match the vision, the vision is likely wrong, or the plan is wrong, or both — bring it up before implementing.
