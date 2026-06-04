# Luna Service — Vision

> The hosted home for Luna. Anyone can sign up and have a real, persistent, fully-isolated Luna agent running for them in the cloud in under sixty seconds — without ever installing anything. Open-source Luna stays open. We run the multi-tenant SaaS that lets people use it without becoming sysadmins.

---

## TL;DR

**Luna Service** is the commercial multi-tenant cloud platform for the open-source [Luna agent](https://github.com/huemorgan/luna). It's a **wrapper, not a fork** — Luna OSS stays pristine and single-tenant; Luna Service is the orchestration, billing, and user-experience layer that runs many isolated Luna instances on behalf of paying users.

**The product:** sign up with Google → wait ~60 seconds → land in your own private Luna at `you.luna.com.ai` (or path-based equivalent on `luna.com.ai`). Your Luna remembers you across sessions, has its own credentials vault, runs its own MCP servers, and eventually writes and executes code in its own sandbox. Other users' Lunas can't see yours, can't touch your data, can't influence what your Luna does.

**The split:**
- **Luna OSS** = the agent. MIT licensed. Anyone can self-host on a $5 VPS.
- **Luna Service** = the SaaS. Private repo. Runs many Lunas, handles signup, billing, lifecycle, isolation, support.

**The bet:** developers will adopt and contribute to OSS Luna; non-developers and convenience-seekers will pay for Luna Service. The OSS funnels into the hosted product. Neither hurts the other.

---

## Why This Exists

Luna OSS is powerful but assumes a competent operator. To self-host you need to:

- Provision Postgres + Redis
- Configure Docker
- Manage LLM API keys
- Set up Alembic migrations
- Run `make setup`, `make api-dev`, `make ui-dev`
- Keep it running and patched
- Set up TLS, a domain, monitoring
- Configure backups
- Update the OSS code when new releases ship

That's fine for developers experimenting. It's a wall for everyone else — and **everyone else is most of the market for an AI agent that handles your credentials, watches your funnels, edits your documents, and writes code on your behalf.**

Luna Service exists to remove every barrier between "I heard about Luna" and "I have a Luna." Sign up. Done. Your Luna is real, isolated, persistent, and ready to use.

---

## The Convictions

### 1. The OSS code does not change to support hosting

Multi-tenancy lives **entirely in the deployment layer**. Luna OSS continues to think of itself as a single-tenant local agent. Hosted Luna achieves isolation through infrastructure (separate processes, separate databases, separate filesystems per user) — not by adding `tenant_id` columns to every Luna table.

This means:
- OSS users see no multi-tenant complexity
- We never have to backport changes from a hosted fork
- A new OSS release flows directly into hosted Luna with no merge work
- Self-hosters always have feature parity with hosted users

If we ever need OSS changes (we will, for the trusted-proxy auth header and pluggable vault key source), they are tracked in OSS as small, generally-useful improvements — not "hosted Luna's fork."

### 2. Each Luna is physically isolated

A user's Luna runs in its **own microVM**, with its **own database schema**, its **own filesystem**, its **own vault encryption key**, and its **own MCP subprocesses**. Logical isolation alone (one process, scoped by `tenant_id`) is unsafe for an agent that handles credentials, runs MCP servers, and will eventually execute arbitrary code.

The cost of physical isolation is higher infrastructure spend per user. We pay that cost because the alternative — a security breach where one user's code execution reads another's vault contents — would end the company.

### 3. Idle Lunas cost nothing

Most users will chat occasionally, not constantly. Most Lunas will be idle 95%+ of the time. We don't pay for compute that isn't being used.

The platform supports **scale-to-zero** with **suspended-state preservation** — a user's Luna VM literally hibernates to disk when idle, costing essentially nothing, and resumes in ~300ms when the user returns. Plugin state, vault key, prompt cache references — all preserved across suspension. The user sees a Luna that's "always there." We see a fleet that costs a tenth of always-on.

### 4. Always-on tier exists for autonomy

The pure scale-to-zero model only works when the user initiates every interaction. The moment a user wants Luna to act on their behalf — fire a scheduled task at 9am, respond to a Slack mention, watch an inbox — Luna must be always-on. This is a **paid feature**, priced to cover its real cost.

This naturally creates a clean pricing ladder:
- **Free:** suspended Luna, chat-only, ~$1-2/month cost to us
- **Pro:** always-on Luna with triggers and autonomy, priced ~$15-25/month
- **Power:** dedicated CPU, larger memory, code execution, priced ~$50-100/month

### 5. Three storage tiers, each used for what it's best at

A Luna needs:
- A **real filesystem** for code it writes and runs (Volume / block storage)
- A **structured queryable database** for conversations, memory, vault, settings (Postgres)
- A **cheap durable blob store** for user uploads, generated artifacts, archives (R2 object storage)

We don't try to make one tier do all three jobs. Trying to put code on object storage breaks `pip install`. Trying to put files in Postgres makes downloads slow and expensive. Trying to query files on a Volume means scanning directories. Each tier does one job well; together they form the storage substrate. Details in `vision/filesystem-architecture.md`.

### 6. User experience is the product

Luna Service competes with self-hosting on convenience. If our UX is worse than self-hosting, technical users will self-host and we get nothing. The UX bar is therefore very high:

- **Signup → working Luna: under 90 seconds.**
- **First chat response: instant** (no perceptible cold start; suspended-to-running is invisible).
- **Mobile is first-class** — most casual users will reach for their phone first.
- **Setup is conversational** — Luna onboards the user through chat, not forms.
- **The OSS chat UI is mounted as-is**, no rebuild, so improvements flow both ways.
- **Failure modes are graceful** — when a Luna crashes, it returns. When LLM quotas hit, the user sees a helpful message, not a 500.

### 7. We never look at user data

This is a trust requirement, not just a marketing claim. The platform's design enforces it:

- **Per-tenant vault encryption keys** mean we cannot decrypt user credentials even if we wanted to (key derived per-tenant, never logged, scoped to that user's runtime only)
- **Per-tenant database schemas** with per-tenant credentials mean platform code can't accidentally read across tenants
- **Operator impersonation requires explicit consent + is audit-logged** (for support cases)
- **No telemetry of conversation content** — only operational metrics (uptime, error rates, token counts)

Users put credentials, secrets, work artifacts, and conversations in their Luna. The product fails the moment they suspect we can see any of it.

### 8. One bill, one relationship, all-inclusive

The user pays Luna Service one monthly amount. That amount covers **everything**: hosting, storage, MCP runtime, and **all LLM usage** across every model and provider Luna can call. There is no "bring your own API key" mode. Users never sign up for Anthropic or OpenAI. They never see a token bill from anyone but us. They never reconcile invoices across vendors.

Inside that single bill, users can pick **any supported model** for any task — Claude Opus/Sonnet/Haiku, GPT-4o/GPT-5, Gemini, etc. Their tier defines a monthly token budget; cheaper models stretch it further, frontier models burn it faster. Same dollar value, their choice.

This is non-negotiable for two reasons:
- **UX:** every successful AI product (ChatGPT, Claude.ai, Cursor, Replit) works this way. BYOK loses users at signup.
- **Margin & control:** owning LLM purchasing lets us optimize routing, negotiate volume rates, and cache aggressively — savings we share with users via better pricing, not lost to vendor fragmentation.

---

## What the User Gets

A signed-up user gets:

| Feature | What it Means |
|---------|---------------|
| **A persistent Luna at a stable URL** | `username.luna.com.ai` or `luna.com.ai/username` — same URL forever. |
| **Cross-session memory** | Luna remembers them, their preferences, their projects, what they told it last week. |
| **Encrypted vault for credentials** | Store API keys, OAuth tokens. Luna uses them via tools, never exposes them to LLM context. |
| **MCP server support** | Connect Luna to any MCP server (their email, calendar, custom tools). Their MCPs only — fully isolated. |
| **Approval engine** | Risky actions (spending, sending messages, deleting things) pause for explicit approval. |
| **Web access** | Search the web, fetch pages, make HTTP requests. |
| **Plugin ecosystem** | Install community plugins, eventually write their own. |
| **File workspace** | Upload files, Luna writes files for them, files persist across sessions. |
| **Code execution (future)** | Luna can write and run Python/Node code in its own sandbox. |
| **Multi-channel (future)** | Talk to your Luna via WhatsApp, Slack, email — same Luna, same memory. |
| **Always-on triggers (paid)** | "Email me a summary every morning at 9." Luna acts autonomously. |

All wrapped in a UI that lives at their URL, looks like a polished app, and Just Works.

---

## What This Is NOT

To be clear about scope, what Luna Service is not:

- **Not a fork of Luna.** We pin a Luna release and consume it as an artifact (container image). When we need OSS changes, we contribute them upstream.
- **Not a competitor to Luna OSS.** Self-hosters are not the enemy. Many will eventually pay us for convenience; some will run their own forever. Both are fine.
- **Not a developer-first product.** Developers will use OSS Luna. Luna Service targets people who want an agent, not a project to maintain. The UX assumes zero infrastructure knowledge.
- **Not a research platform.** We host production agents for real users. New experimental features go through OSS first.
- **Not Cursor / Copilot.** Luna is an agent that does work, not an IDE assistant.
- **Not a "Luna API."** The API surface is internal between control plane and Luna instances. If we expose APIs later, they're separate, designed, and documented — not the internal protocol.
- **Not a marketplace platform initially.** Plugins are discoverable but installation is curated. A free-for-all plugin marketplace is a future consideration, not v1.

---

## High-Level Architecture

```
                                  USER
                                   │
                                   │ HTTPS / WebSocket / SSE
                                   ▼
                  ┌────────────────────────────────────┐
                  │     CONTROL PLANE  (Render)        │
                  │  ────────────────────────────       │
                  │  • Marketing site (luna.com.ai)    │
                  │  • Signup (Google OAuth)            │
                  │  • Account & user management        │
                  │  • Billing (Stripe)                 │
                  │  • Provisioning new Lunas           │
                  │  • Router (incoming → user's Luna)  │
                  │  • Wake/sleep orchestrator          │
                  │  • Admin/support dashboard          │
                  │                                      │
                  │  Stack: FastAPI/Next.js + Render PG │
                  └─────────────┬──────────────────────┘
                                │
                                │ Internal RPC + reverse proxy
                                │ (injects X-Luna-User header)
                                ▼
                  ┌────────────────────────────────────┐
                  │     LUNA FLEET  (Fly Machines)     │
                  │  ────────────────────────────       │
                  │                                      │
                  │  ┌──────────────┐ ┌──────────────┐ │
                  │  │ user_abc     │ │ user_xyz     │ │
                  │  │ Luna VM      │ │ Luna VM      │ │
                  │  │ [suspended]  │ │ [running]    │ │
                  │  │ + Volume     │ │ + Volume     │ │
                  │  └──────────────┘ └──────────────┘ │
                  │  ... thousands of microVMs ...      │
                  │                                      │
                  │  Each = unmodified OSS Luna image   │
                  │  Each = own DB schema + Volume      │
                  │  Each = own vault key (per-tenant)  │
                  └──────┬────────────────────┬────────┘
                         │                    │
              shared DB  │                    │  shared object store
                         ▼                    ▼
        ┌─────────────────────────────┐  ┌───────────────────────┐
        │  Render Postgres + pgvector │  │ Cloudflare R2 (S3-like)│
        │  ───────────────────────── │  │ ───────────────────── │
        │  • Schema-per-tenant       │  │ • tenant/{id}/uploads/ │
        │  • Per-tenant scoped role  │  │ • tenant/{id}/archive/ │
        │  • Conversations, memory,  │  │ • shared/marketplace/  │
        │    vault, identity         │  │ • Free egress to web   │
        │  • HNSW index for memory   │  │                        │
        │    semantic recall         │  │                        │
        │  • One cluster, many tenants│  │                       │
        └─────────────────────────────┘  └───────────────────────┘
```

**Key flows:**

1. **Signup:** Browser → Render control plane → Google OAuth → create User + Account → Render creates Postgres schema for tenant → Render calls Fly API to spin up Luna Machine with tenant-scoped env → Luna boots, runs migrations, ready. User redirected to their Luna URL.

2. **Chat:** Browser → Render router → identifies user's account & agent → wakes Luna if suspended (~300ms) → reverse-proxies with `X-Luna-User` header → Luna handles normally, streams SSE back through the proxy.

3. **File upload:** Browser → Render presigned-URL endpoint → direct upload to R2 (`tenant/abc/uploads/file.pdf`) → metadata row inserted in tenant's Postgres schema → Luna sees the file in its UI.

4. **File download:** Browser requests → Render generates signed R2 URL → browser fetches directly from Cloudflare CDN → Luna never touches the bytes.

5. **Scheduled trigger (paid tier):** Render scheduler fires at scheduled time → calls Fly API to wake user's Luna → POSTs trigger event → Luna runs the task → re-suspends after idle.

---

## Hosting Strategy: Why Render + Fly, Not One Cloud

**Render handles the control plane.** Render is excellent at "deploy a normal web app and never think about it again." The control plane is a normal web app — Postgres-backed, single deployment, low-traffic per-request, occasional bursts. Render's developer experience makes this trivial. Render Postgres handles user accounts, billing records, the agent registry — all small, structured, transactional data.

**Fly handles the Luna fleet.** Fly Machines provide what nothing else does cheaply: API-driven microVM provisioning with suspend/resume-to-disk. This is the exact primitive a multi-tenant agent platform needs. Render's services can't suspend cheaply; AWS Lightsail can't suspend at all; bare VPSes can't be provisioned in seconds. Fly is purpose-built for this.

**Could we do it all on Fly?** Yes, and we may eventually. Fly Machines work fine for the control plane too. But Render's polish for "boring web app" workloads is meaningfully better than Fly's, and the control plane benefits from that. Splitting two specialized clouds (each picked for one job) is operationally simple — they communicate via HTTPS APIs only.

**Could we do it all on Render?** No, not at the per-user fleet level. Render has no scale-to-zero hibernation, no fast API-driven container creation, no per-Machine suspend-to-disk. Trying would mean either always-on Lunas (expensive — $5+ per user 24/7) or multi-tenant Lunas inside one Render service (insecure — one process for all users, vault keys all in memory together, kills code execution as a future feature).

The pragmatic split: **Render for the always-on bits, Fly for the elastic bits.**

---

## The User Experience Bar

We're competing with two alternatives:
1. **Self-hosting** — free if you know how, painful if you don't
2. **ChatGPT / Claude / generic chat** — slick, free-ish, but not an agent (no memory, no vault, no MCP, no code, no triggers)

Our pitch is: **an agent as polished as ChatGPT, as private as self-hosting, that actually does things instead of just talking.**

### Latency Targets

| Action | Target | Why |
|--------|--------|-----|
| Signup → first usable Luna | < 90 seconds | Faster than a Stripe checkout. Most flows lose users after 60s of waiting. |
| First chat message after idle | < 800ms to first token | ~300ms wake + ~500ms to LLM first token. Indistinguishable from always-on. |
| Subsequent chat messages | < 500ms to first token | Just the LLM latency. |
| Page load (chat UI) | < 1s | Standard SaaS web app target. |
| File upload (10MB) | < 5s | Direct to R2, no proxy through our infra. |
| Triggers (paid tier) | < 200ms event handling | Always-on Luna processes the event without wake. |

### Failure Mode Standards

| Scenario | What user sees |
|----------|---------------|
| Luna crashes mid-conversation | "Reconnecting..." → recovered context, message resent automatically |
| LLM rate limit hit | Friendly message ("I'm at my limit for the day, upgrade to Pro for more"), not an HTTP error |
| MCP server fails | Tool returns specific error to Luna, Luna explains to user, user can retry or disable that MCP |
| Vault key corrupted | Clear message + path to recovery; offer to restore from snapshot if available |
| Account suspended for non-payment | 7-day grace period with reduced functionality, then read-only access, then archived (not deleted) for 30 days |

### Mobile

Mobile is not an afterthought. The chat UI must work cleanly on iOS Safari and Android Chrome from day one. PWA installation should be one tap. Push notifications (for approval requests and triggered actions) come later as a native mobile app, but the responsive web experience must already be excellent.

---

## Pricing Tiers (Provisional)

Pricing shapes architecture. The runtime model maps cleanly to three tiers:

| Tier | Cost to Us | Price | Includes |
|------|-----------|-------|----------|
| **Free** | ~$2-4/user/mo | $0 | Suspended Luna; small monthly token budget on cheap models; web access; vault for ≤3 credentials; 1GB Volume; chat-only (no triggers) |
| **Pro** | ~$10-20/user/mo | $29/mo | Always-on Luna; generous token budget across model tiers; triggers/cron; unlimited credentials; 5GB Volume; MCP servers; multi-channel |
| **Power** | ~$40-80/user/mo | $99/mo | Dedicated CPU; large token budget incl. frontier models; 20GB Volume; code execution; priority support; SLA |
| **Enterprise** | Custom | Custom | Dedicated Postgres; SSO; custom data residency; audit exports; volume LLM commitments |

### One Bill. No BYOK. Pick Any Model.

Luna Service is **all-inclusive**. The user pays one monthly bill that covers everything: hosting, storage, MCP runtime, and **all LLM usage**. There is no "bring your own key" option. Users never enter an Anthropic/OpenAI/Google key into the product, never see an LLM provider bill, never deal with rate limits from multiple vendors, never reconcile two invoices.

**Why no BYOK:**

1. **It's a worse user experience.** BYOK means signup → "now go create an Anthropic account, generate a key, paste it here, top up credits, configure rate limits..." We lose users at every step. The whole point of a hosted service is removing this friction.
2. **It splits the relationship.** With BYOK the user has a relationship with us AND with three LLM vendors. When something breaks, they don't know who to blame. With one bill, we own the experience end-to-end.
3. **It complicates support.** "Why is my Luna slow?" — is it our infra, their key's rate limit, their billing cap with OpenAI, their model choice? With one bill, we know the whole stack.
4. **It removes our ability to optimize.** When we own LLM purchasing, we can route requests across providers, negotiate volume discounts, use cheaper models for cheap tasks, cache aggressively across our own infrastructure. With BYOK, we lose all of that.
5. **It's how every successful AI product works.** ChatGPT, Claude.ai, Perplexity, Cursor, Replit Agent — none of them ask users to bring keys. The companies that tried (early Cody, some open agent platforms) ended up adding hosted billing because users wanted it.

**Model choice stays open:**

Users can switch between models freely from their Settings — Anthropic Claude (Opus, Sonnet, Haiku), OpenAI GPT-4o / GPT-5, Google Gemini, etc. The model selection is per-task and per-conversation. We bill **the same way regardless of which model they pick**: every tier includes a monthly token budget calibrated to provide good value at typical mid-tier model usage (e.g., Sonnet-class).

Users who want to use cheaper models stretch their budget further; users who want frontier models burn through it faster — same dollar value, their choice. We display a clear usage meter so they always know where they stand.

**When budget runs out:**

- **Free tier:** Luna pauses LLM responses, asks them to upgrade. Other features (memory, vault, file management) still work.
- **Paid tiers:** soft cap warning at 80% → at 100%, user can either wait until next cycle, top up with usage credits, or upgrade tier. Never an unexpected bill.

**Enterprise can negotiate** model pools, volume commits, and dedicated capacity — but everything still flows through our single bill.

### How LLM Costs Are Tracked Internally

Even though users see one bill, internally we meter every token through every provider. Luna's existing `plugin-cost` already tracks this per-conversation, per-action. We aggregate at the account level for:

- **Usage display** to the user (their meter)
- **Capacity planning** (which models are popular, where to negotiate)
- **Tier rebalancing** (if Free users average $5 in LLM costs instead of $2, we adjust)
- **Anomaly detection** (a runaway loop burning tokens triggers a hard stop and notification)

The user never sees this metering complexity — they see a meter ("you've used 38% of your monthly tokens") and a clean monthly invoice from us.

---

## Authentication

**Sign-in is Google OAuth only.** No email/password, no magic links, no GitHub, no Apple in v1. Google sign-in is universal, eliminates password storage entirely, gives us verified emails for free, and is what most of our target users expect from a modern SaaS.

**OAuth app ownership:** The OAuth 2.0 client is registered under the **`novalystrix.ai`** Google Workspace organization. This is the legal/operational entity that owns the application. Users see "Luna Service by Novalystrix" on the consent screen; the app's OAuth credentials live in a Google Cloud project inside that org, managed by Novalystrix-controlled accounts.

**Who can sign up:** open to any Google account (Gmail, Google Workspace tenants, etc.). We do not restrict by domain. Anyone with a Google identity can become a Luna Service user.

**What we store:**
- `google_sub` (stable Google user ID) — primary auth identifier
- `email` (verified by Google)
- `name` and `avatar_url` (from Google profile, refreshable)

**What we don't store:**
- Passwords (don't exist)
- Refresh tokens for Google APIs (we only need identity, not Drive/Gmail access)
- Any Google-internal data

**Session model:** server-side sessions via HttpOnly/Secure/SameSite cookies after `id_token` verification. JWT-in-localStorage is avoided. Session timeout configurable per account (default 30 days, refreshed on activity).

**Account selection:** because a User can belong to multiple Accounts (consultant in two companies, etc.), every authenticated request resolves to `(user, active_account)`. The active account is chosen at login or via a switcher in the UI; the session carries it.

**Future additions (not v1):**
- **Workspace SSO (SAML/OIDC) per Account** for Enterprise tier — a company can connect their own identity provider so their employees sign in via their corporate SSO
- **Domain capture** — "anyone @company.com automatically joins Account X" for Workspace-based organizations
- **Apple/GitHub OAuth** if usage data shows meaningful demand from segments that don't have Google accounts

These are documented in the data model now (`Membership.role`, `Invitation`, etc.) so adding them later doesn't require schema changes.

---

## Open-Source Strategy

Luna Service is the **commercial home** for Luna. The OSS project benefits:

- **Funding:** Luna Service revenue funds OSS development. Maintainers can work on Luna full-time.
- **Production usage:** Every hosted Luna is a stress test. Bugs and edge cases get found and fixed in OSS.
- **Plugin ecosystem:** Hosted users will request and pay for plugins. Plugin authors can build for the largest Luna deployment. Most plugins remain OSS; some are commercial.
- **Marketing:** Luna Service is the visible front of the project. People discover Luna via Luna Service and many install OSS too.

OSS Luna stays MIT and complete. We never gate features behind hosted-only. We never artificially limit OSS. If hosted Luna gets a new feature, the OSS Luna it runs on top of gets it too.

The few things kept proprietary are:
- The control plane code itself (signup, billing, provisioning logic — has no value to OSS users)
- Vertical plugin packs we sell (e.g., Marketing Suite knowhow)
- Operational dashboards and admin tools

---

## Agent Fleet Dashboard & Team Management

The control plane on Render.com is not just a routing layer — it is a **full management surface** for users' agent fleets. The dashboard is where users create, monitor, configure, and retire agents. Fly.io runs the agents; Render runs the management experience.

### Dashboard: Agent Fleet Management

Users don't get one Luna by default. They get an **empty workspace** and the power to create agents on demand.

**Core dashboard capabilities:**

- **Agent list** — see all agents in the account: name, status (running / stopped / provisioning / error), uptime, last active, monthly cost
- **Create agent** — explicit "New Agent" action provisions a Fly Machine. Clear progress indicator, explicit error reporting if Fly provisioning fails. Users choose a name and (later) a template/preset.
- **Agent detail view** — per-agent panel: start/stop/restart controls, configuration, logs preview, cost breakdown, connection URL
- **Destroy agent** — permanent removal with confirmation. Tears down Fly Machine, archives DB schema, cleans up
- **Bulk operations (future)** — stop all agents, restart fleet, export agent configs

This is a fleet management tool. Power users will run 5, 10, 50 agents — one per project, per client, per workflow. The dashboard must scale to hundreds of agents per account without becoming unusable.

### Cost & Billing Visibility

Every agent has a cost. The dashboard makes costs visible and controllable:

- **Per-agent cost meter** — how much this agent has consumed this billing cycle (compute time, LLM tokens, storage)
- **Account-level spend overview** — total monthly spend, broken down by agent, by cost category (compute, LLM, storage)
- **Budget controls (future)** — set per-agent or per-account spending caps. Agent pauses or downgrades when budget is exhausted.
- **Billing page** — Stripe integration. Payment method, invoices, plan upgrades

### Teams & Collaboration

Agents belong to accounts, not to individual users. An account is a team/company:

- **Roles** — owner, admin, member, viewer. Owners manage billing and invitations. Admins can create/destroy agents and manage members. Members can use agents. Viewers can observe but not interact.
- **Invitations** — invite by email. Invited users sign in with Google and are added to the account.
- **Shared agent access** — all team members with appropriate roles can use any agent in the account. Access control is at the account level, not per-agent (per-agent ACLs are a future enhancement).
- **Activity audit (future)** — who did what, when. Agent creation, configuration changes, team membership changes — all logged.
- **Multi-account support** — a single Google user can belong to multiple accounts (personal + work). Account switcher in the UI header.

### Agent Marketplace (Future)

A marketplace for agent configurations, templates, and plugin bundles:

- **Agent templates** — pre-configured agent setups: "Marketing Agent," "Developer Agent," "Research Agent." Each template defines a set of plugins, system prompts, and configurations.
- **Community templates** — users can publish their agent setups as templates for others.
- **Plugin marketplace** — browse, install, and manage plugins per-agent. Some free (OSS), some paid (commercial packs).
- **One-click deploy** — pick a template from the marketplace → agents is provisioned with that config automatically.

The marketplace is not v1. But the dashboard data model (agents have configurations, configurations are composable) is designed to support it cleanly when the time comes.

---



Luna's roadmap (see `luna/plans/FANTASIES.md`) includes things that change the platform's shape over time. We must build the platform such that none of these require re-architecting:

| Luna Capability | Platform Implication |
|-----------------|---------------------|
| **Code generation & execution** | Per-Luna Volume is mandatory (real filesystem). Sandbox at the VM level (already what Fly Machines provide). |
| **Browser automation (Browserbase, etc.)** | Per-user browser sessions, integrated with their Luna's vault. May need stateful proxy or per-tenant browser pool. |
| **Buying domains, credit cards** | Per-Luna spend controls. Account-level budget enforcement at the platform layer. Audit log of all spend events. |
| **Mobile app** | Native iOS/Android shells against our existing API. Push notifications for approvals. |
| **Multi-channel (WhatsApp, Slack)** | Per-Luna channel routing through control plane. Always-on tier required (channels = inbound triggers). |
| **Cross-agent communication** | Control plane brokers agent-to-agent invites. Two Lunas in different accounts can join a shared session. |
| **Behavioral profiling** | Sensitive — profile data must stay in user's tenant DB, never aggregated cross-tenant without explicit consent. |
| **Self-modification (Luna writes its own code)** | Each Luna has its own Volume for plugin code. Updates contained within the user's tenant. |
| **Knowhow packs** | Marketplace storage in shared R2; entitlements checked by control plane; installed per-Luna into their DB. |

Each of these layers onto the same fundamental architecture: **isolated VMs per Luna, shared data layer with tenant scoping, control plane orchestrates lifecycle, R2 for shared/cold assets.** Nothing in the roadmap requires us to redesign the foundation.

---

## What Success Looks Like

In one year:
- **OSS Luna** has 5,000+ GitHub stars and an active plugin community
- **Luna Service** has 10,000+ free tier users and 1,000+ paid users
- **Infrastructure spend** is ~$15-25K/month, covered ~3x by subscription revenue
- A user can go from "I heard about Luna" to "I'm using my Luna" in under two minutes
- A self-hoster can run the same Luna we host, with the same features, on a $5 VPS
- Plugin authors can develop locally against OSS and publish for hosted users to install
- Support load is low because the product is reliable, the UX is clear, and the docs are good

---

## The Path

This vision is the destination. Getting there is a sequence of phases, each shippable on its own. The next document — `plans/` — breaks down the implementation order, starting with the absolute minimum needed to provision and serve a single hosted Luna.

We won't build everything at once. We build the smallest thing that proves the architecture works end-to-end (signup → provisioned Luna → real conversation → bill the user), and we add capability from there. Each layer is designed to extend cleanly into the layers above it.

---

*Related documents:*
- `vision/filesystem-architecture.md` — the three-tier storage model (Postgres + R2 + Volume)
- `luna/vision/vision.md` — Luna OSS vision (the agent itself)
- `luna/plans/luna-cloud/plan.md` — Luna's own plan for what hosted Luna needs from OSS (the seam)
- `luna/plans/FANTASIES.md` — Luna's future capabilities roadmap
