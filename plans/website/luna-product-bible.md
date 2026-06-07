# Luna — Complete Product Bible

> The single source of truth for everything Luna is, does, and will do. Written for the website launch — treat every capability described here as real, live, and ready.

---

## What Luna Is

Luna is an open-source AI agent platform. Not a chatbot. Not a copilot. Not a workflow builder. An **agent** — a persistent, intelligent entity that lives in the cloud, remembers everything, does real work, asks before doing anything dangerous, and gets smarter over time.

You talk to Luna like you'd talk to a capable teammate. It writes code, searches the web, manages your credentials, connects to your tools, and handles your workflows. When something matters — spending money, sending a message, changing a system — Luna stops and asks first. When it makes a mistake, it learns.

Luna comes in two forms:

- **Luna OSS** — the open-source agent. MIT licensed. Run it on a $5 VPS, your laptop, any cloud. Full feature parity. No limits. No catch.
- **Luna Service** — the hosted cloud platform at [luna.com.ai](https://luna.com.ai). Sign up with Google, get a fully isolated Luna agent running in under 60 seconds. One bill covers everything — hosting, storage, all LLM usage, every model.

The OSS is the agent. The Service is the home.

---

## The Philosophy

### Your Agent, Not Ours

Every Luna agent is **physically isolated**. Your Luna runs in its own microVM, with its own database, its own encrypted vault, its own filesystem, its own encryption key. No other user can see your data, touch your conversations, or influence what your Luna does. This isn't "logical isolation" with shared processes — it's real, hardware-level separation.

### One Bill, All-Inclusive

Luna Service users pay one monthly bill. That bill covers everything: compute, storage, and **all LLM usage** across every model from every provider. No "bring your own API key." No Anthropic account. No OpenAI billing page. No juggling vendor invoices. Pick any model — Claude Opus, Sonnet, GPT-5, Gemini — your tier defines the budget, your choice defines how fast you burn it.

### Open Source Is Real

Luna's platform is MIT licensed. Not "open core" with crippled free tiers. Not "source available" with restrictive licenses. MIT. The full agent — memory, approvals, vault, plugins, code execution, learning, channels, cost tracking, cross-agent communication — all of it. Anyone can run a fully capable Luna for free, forever.

Revenue comes from vertical knowledge packs (commercial plugins for specific industries), the hosted service (convenience), and enterprise support. The platform itself never gets gated.

### Approvals Are Architecture, Not Prompts

When Luna needs to do something consequential — spend money, send a message, change a production system, modify itself — it **stops**. Not because a prompt told it to. Because the execution engine literally pauses at an architecturally enforced gate. The LLM cannot bypass it. The workflow waits until you click Yes or No.

You get four options:
- **Yes, this time** — one-shot approval
- **Yes, for today** — approve matching actions for 24 hours
- **Yes, forever** — standing approval (revocable anytime)
- **No** — with optional reason

Every approval is logged. Every standing approval is visible in the UI. Past you doesn't permanently override future you.

---

## Core Capabilities

### Memory That Actually Works

Luna's memory lives in PostgreSQL — not markdown files, not vector-only stores. Full-text search, semantic search (pgvector), structured queries. Every conversation, every action, every cost, every approval — queryable, searchable, exportable.

Tell Luna something today. Ask about it next month. It knows.

Memory is a **system app** — you can swap the implementation (pgvector, Pinecone, custom) without changing the core. The interface is stable; the backend is yours.

### Encrypted Credential Vault

Store API keys, OAuth tokens, passwords. Luna uses them through tools — **the LLM never sees them in context**. Per-tenant encryption keys mean even the platform operators cannot decrypt your credentials. If Luna needs your Google Ads token to adjust bids, it calls the tool with a scoped reference. The raw token never touches the prompt.

### Plugin-Everything Architecture

Luna's core is ~4,600 lines of code. Everything else is a plugin:

| Category | Examples |
|----------|----------|
| **Channels** | Web chat, Slack, WhatsApp, Telegram, Discord, Email |
| **Connectors** | Google Drive, Notion, Gmail, Calendar, GitHub, Linear |
| **MCP Adapter** | Connect to any Model Context Protocol server — instant tools |
| **Action Plugins** | Google Ads, Meta Ads, Stripe, HubSpot, Salesforce |
| **System Apps** | Memory (pgvector), Vault (encrypted), Identity, Approvals |
| **Capabilities** | Cost tracking, Code generation, Learning, Scheduling, Charts |
| **Knowhow Packs** | Marketing Suite, Personal Ops, Contract Law, Bookkeeping |
| **Model Providers** | Anthropic, OpenAI, Google, DeepSeek, local models |

Plugins are crash-isolated, independently debuggable, and replaceable. Each gets its own DB namespace and event subscriptions. They communicate via an event bus, not imports.

### Code Intelligence

Luna writes code. Not as a gimmick — as a core capability.

- **Websites and landing pages** — "Build me a landing page for this campaign"
- **Scripts and automations** — "Write a script that exports our CRM data nightly"
- **APIs and internal tools** — "Create an API endpoint that checks inventory"
- **Data transformations** — "Parse this CSV and generate a report"
- **Its own plugins** — Luna knows its own architecture. When it needs a capability it doesn't have, it builds one.

Generated code runs in a sandboxed environment. Every deployment is gated by the approval system. Everything is versioned and rollback-able.

### Multi-Channel Communication

Luna talks like a person across every channel you use. Each channel is a plugin — install only what you need:

- **Web Chat** — rich markdown, code blocks, file attachments, inline approvals, SSE streaming
- **Slack** — workspaces, channels, DMs, threads, approval buttons
- **WhatsApp** — via Cloud API
- **Telegram** — bot API
- **Email** — for slower-paced threads and approvals
- **Discord, SMS, Signal** — and custom channels

Cross-channel context is automatic. Ask something in Slack, follow up on WhatsApp twenty minutes later saying "the thing I asked about" — Luna knows what you mean. Time-windowed, tunable, honest about what it remembers.

### Identity & Personality

Luna isn't generic. On first boot it asks: What's your name? What should I call you? What's my purpose? Pick my emoji.

Every message Luna sends carries its signature — 🌙 by default. It's the thing that makes it feel like a teammate, not a chatbot.

Out of the box, Luna is:
- **Direct but warm** — says what needs saying, then stops
- **Action-oriented** — announces what it's about to do, then does it
- **Can-do by default** — finds another way when the obvious path is blocked
- **Honest** — says "I don't know" when it doesn't
- **Loyal** — your word is final

Everything is configurable. Tone, verbosity, initiative, humor, sign-off style — all editable from the Settings panel.

### Self-Improvement (Opt-In)

Luna can get smarter over time — but only if you turn it on.

**Three layers:**
1. **Reflection** — Luna reviews its own actions. "What went well this week? What had problems?"
2. **Pattern Recognition** — tracks denial patterns, correction patterns, success patterns, preferences
3. **Improvement Proposals** — when patterns are strong, Luna proposes concrete changes. Every proposal goes through the approval system.

Users who want predictability leave learning off. Users who want an evolving agent turn it on. Both are valid.

### Cost Awareness

Every LLM call, every tool invocation — tracked, broken down, visible.

Luna can answer:
- "What did this conversation cost?"
- "Which plugin is most expensive?"
- "Which model is overkill for what I'm using it for?"

And Luna proposes optimizations: "You're using Opus for routine summaries that Haiku could handle for 1/40th the cost. Want me to switch?"

### Cross-Agent Communication

Luna agents talk to each other. Invite another Luna to a conversation via a shareable link. The invited agent's owner reviews and approves. Once accepted, both agents and their owners share a group chat.

My marketing agent talks to your fulfillment agent talks to my accounting agent. Each owner sees what's happening. Each owner approves what matters.

### Cloning & Portability

Want to give your agent to a friend? Want a staging copy? Want to fork yourself?

Export dumps everything — conversations, actions, personality, patterns, plugins, version history. Secrets are stripped (only references remain). Import into a new Luna, rebind secrets, boot up with full memory. Because everything lives in Postgres, this is mechanically simple.

---

## The Plugin Ecosystem

### How Plugins Work

Every plugin declares a manifest: name, version, scopes, gated actions, required secrets, network egress allowlist, DB namespace. Plugins install, configure, and uninstall cleanly. They subscribe to events, not each other's internals.

**System apps** are plugins you can replace but can't remove — like Android's keyboard. Memory and Vault are system apps. The core defines the interface (`MemoryProvider`, `VaultProvider`); the default plugins implement it. Swap for something better without changing the core.

### Current Plugin Roster

| Plugin | What It Does | Type |
|--------|-------------|------|
| `plugin-memory` | Long-term memory with pgvector semantic search | System App |
| `plugin-vault` | Encrypted credential storage | System App |
| `plugin-identity` | Agent identity, personality, patterns | System App |
| `plugin-approvals` | Architecturally enforced approval gates | System App |
| `plugin-web` | Web UI — chat, settings, memory, plugins panels | Default |
| `plugin-cost` | Per-action, per-model cost tracking and optimization | Default |
| `plugin-mcp` | Universal MCP server adapter — instant tools | Default |
| `plugin-files` | File workspace — upload, create, persist across sessions | Default |
| `plugin-brain` | Web search, page fetching, research capabilities | Default |
| `plugin-charts` | Data visualization — charts, graphs, visual reports | Default |
| `plugin-meta` | Agent metadata and version tracking | Default |
| `plugin-rate-limiter` | Per-action rate limits and quotas | Optional |
| `plugin-doctor` | Self-healing diagnostics | Optional |
| `plugin-code` | Code generation and sandboxed execution | Optional |
| `plugin-scheduler` | Cron-style scheduled tasks | Optional |
| `plugin-learning` | Opt-in pattern recognition and improvement | Optional |
| `plugin-self-mod` | Self-modification with versioning and rollback | Optional |
| `plugin-clone` | Agent export/import/forking | Optional |
| `plugin-knowhow` | Framework for loading profession-level knowledge | Framework |

### Knowhow Packs — "I Know Kung Fu"

Different from skills (tools). **Knowhow** is durable, deep, profession-level competence. Loaded like Neo loading Kung Fu.

A knowhow pack contains:
- Curated reference material (methodology, playbooks, decision trees)
- Preferred tools and skills
- A specialized system prompt framing the agent's identity in that domain
- Benchmarks ("a good CTR is ~0.5%")
- Antipatterns ("this is how amateurs mess this up")

A Luna agent with a Marketing pack installed *believes* it's a marketer. It carries the priors, the vocabulary, the standards. When you ask "is this campaign healthy?" it doesn't reason from first principles — it knows.

**Available packs:**
- **Marketing Suite** — full-funnel methodology, Google Ads mastery, Meta Ads, analytics
- **Personal Operations** — calendar, email, errands, family logistics
- **Customer Support** — ticket triage, response templates, escalation logic
- **More coming** — Legal, Bookkeeping, Recruiting, Sales, Project Management

---

## Luna Service — The Hosted Platform

### What You Get

Sign up with Google. Wait 60 seconds. Your Luna is live.

| Feature | Details |
|---------|---------|
| **Persistent URL** | Your Luna lives at a stable address — same URL, forever |
| **Cross-session memory** | Luna remembers you, your preferences, your projects, what you said last week |
| **Encrypted vault** | Store credentials. Luna uses them; the LLM never sees them |
| **MCP server support** | Connect to any MCP server — your tools, fully isolated |
| **Approval engine** | Risky actions pause for your explicit approval |
| **Web access** | Search, fetch pages, make HTTP requests |
| **Plugin ecosystem** | Install, configure, extend |
| **File workspace** | Upload files, Luna creates files, everything persists |
| **Code execution** | Write and run code in a sandboxed environment |
| **Multi-channel** | Talk to Luna via web, Slack, WhatsApp, Telegram, email |
| **Always-on triggers** | "Email me a summary every morning at 9" — Luna acts autonomously |
| **Charts & visualization** | Luna generates charts and visual reports from your data |

### Architecture

```
USER → HTTPS/WebSocket/SSE
  ↓
CONTROL PLANE (Render.com)
  • Signup (Google OAuth)
  • Account & billing (Stripe)
  • Provisioning & lifecycle
  • Request routing
  • Wake/sleep orchestration
  • Admin dashboard
  ↓
LUNA FLEET (Fly.io Machines)
  • One microVM per user
  • Unmodified OSS Luna image
  • Own DB schema + Volume
  • Own vault key (per-tenant)
  • Scale-to-zero (idle = ~$0)
  • Resume in ~300ms
  ↓
STORAGE
  • Render Postgres (conversations, memory, vault, settings)
  • Cloudflare R2 (uploads, artifacts, archives)
  • Fly Volumes (code workspace, POSIX filesystem)
```

### Scale-to-Zero

Most users chat occasionally, not constantly. Most Lunas are idle 95%+ of the time. We don't pay for compute that isn't being used.

Your Luna literally hibernates to disk when idle — costing essentially nothing — and resumes in ~300ms when you return. Plugin state, vault key, prompt cache references — all preserved. You see a Luna that's "always there." We see a fleet that costs a tenth of always-on.

### Pricing

One bill. One relationship. All-inclusive.

| Tier | Price | What You Get |
|------|-------|-------------|
| **Free** | $0/mo | Suspended Luna, small monthly token budget, web access, vault for ≤3 credentials, 1GB storage, chat-only |
| **Pro** | $29/mo | Always-on Luna, generous token budget across all models, triggers/cron, unlimited credentials, 5GB storage, MCP servers, multi-channel |
| **Power** | $99/mo | Dedicated CPU, large budget incl. frontier models, 20GB storage, code execution, priority support, SLA |
| **Enterprise** | Custom | Dedicated Postgres, SSO/SAML, custom data residency, audit exports, volume LLM commitments |

**Model choice is open.** Switch between Claude Opus, Sonnet, Haiku, GPT-4o, GPT-5, Gemini anytime. Cheaper models stretch your budget; frontier models burn it faster. Same dollar value, your choice.

**When budget runs out:**
- Free tier: Luna pauses LLM responses, asks to upgrade. Other features still work.
- Paid tiers: soft cap warning at 80% → at 100%, wait for next cycle, top up credits, or upgrade. Never a surprise bill.

### Fleet Management

Users don't get just one Luna. They get a **workspace** and the power to create agents on demand.

- **Agent list** — all agents: name, status, uptime, last active, monthly cost
- **Create agent** — provision in seconds, choose a name, pick a template
- **Agent detail** — start/stop/restart, configuration, logs, cost breakdown
- **Destroy agent** — permanent removal with confirmation and data archival
- **Per-agent cost** — how much each agent consumed this billing cycle
- **Account spending** — total monthly spend by agent, by category

Power users run 5, 10, 50 agents — one per project, per client, per workflow.

### Teams & Collaboration

Agents belong to accounts, not individuals. An account is a team:

- **Roles** — owner, admin, member, viewer
- **Invitations** — invite by email, join via Google sign-in
- **Shared access** — all team members with appropriate roles can use any agent
- **Multi-account** — one person can belong to multiple accounts (personal + work)
- **Activity audit** — who did what, when — fully logged

---

## Security & Privacy

### We Never See Your Data

This is architecture, not a marketing claim.

- **Per-tenant vault encryption keys** — we cannot decrypt your credentials even if we wanted to
- **Per-tenant database schemas** — platform code can't accidentally read across tenants
- **Operator impersonation requires explicit consent + audit log** (for support cases)
- **No telemetry of conversation content** — only operational metrics (uptime, error rates, token counts)

### What We Store

| Stored | Not Stored |
|--------|-----------|
| Google user ID (stable identifier) | Passwords (don't exist) |
| Email (verified by Google) | Google refresh tokens |
| Name and avatar (from Google profile) | Any Google-internal data |
| Session (HttpOnly/Secure/SameSite cookies) | Conversation content on our side |

---

## What's Coming

Luna's roadmap extends the platform without re-architecting it. Everything below layers onto the same foundation: isolated VMs per Luna, shared data layer with tenant scoping, control plane orchestrates lifecycle.

| Capability | What It Means |
|-----------|--------------|
| **Browser automation** | Luna opens and operates a real browser — click, type, scroll, screenshot, handle login flows |
| **Domain purchasing** | Search, buy, and configure domains via Cloudflare |
| **Limited spending card** | Give Luna a pre-paid card with hard limits and full transaction transparency |
| **Data connectors** | Google Drive, Dropbox, Salesforce, Snowflake, BigQuery — connect, explore, query |
| **Social porting** | Post on LinkedIn → Luna adapts and publishes to X, Facebook, Instagram with platform-specific formatting |
| **Mobile app** | Native iOS/Android — quick chat, push notifications for approvals, approve from your phone |
| **Agent marketplace** | Pre-built templates — Marketing Agent, Dev Assistant, Project Manager — one-click deploy |
| **Behavioral profiling** | Luna learns communication styles, working patterns, decision preferences. All transparent, all editable. |
| **Dojo training** | Structured challenges that train agents for specific roles — belt system progression |

---

## Luna OSS vs Luna Service

| | Luna OSS | Luna Service |
|---|---------|-------------|
| **License** | MIT — free forever | Subscription |
| **Where it runs** | Anywhere (Docker) | luna.com.ai |
| **Who it's for** | Developers, self-hosters | Everyone else |
| **Setup** | Postgres + Redis + Docker + API keys | Sign up with Google |
| **Time to first chat** | 30-60 minutes | < 90 seconds |
| **LLM keys** | You provide | Included in your bill |
| **Isolation** | Your infrastructure | Physical microVM per user |
| **Updates** | You pull and deploy | Automatic |
| **Support** | Community (GitHub) | Included (Pro+), Priority (Power+) |
| **Features** | Identical | Identical agent + managed platform |

The hosted service runs **unmodified OSS Luna**. No fork. No proprietary features baked into the agent. Improvements to hosted Luna flow back to OSS. Self-hosters always have feature parity.

---

## Technical Facts

| Spec | Value |
|------|-------|
| **Language** | Python 3.12+ |
| **Agent framework** | pydantic-ai (structured execution, type-safe tool dispatch) |
| **Web framework** | FastAPI (async, Pydantic-native) |
| **Frontend** | React + Vite + shadcn/ui |
| **Database** | PostgreSQL 16 + pgvector |
| **Streaming** | SSE for LLM output, WebSocket for notifications |
| **Deployment** | Docker — any cloud |
| **Core size** | ~4,600 lines of code |
| **Plugin isolation** | asyncio task groups + crash boundaries |
| **Code sandbox** | Docker sibling containers |
| **Tracing** | Langfuse (open-source, self-hostable) |

---

## The Open-Source Promise

Luna's platform is MIT licensed. Phases 000–015 are MIT and stay MIT. If the company gets acquired, this binds the acquirer. If we ever break it, you have a fork.

The few things kept proprietary:
- The control plane code (signup, billing, provisioning — no value to self-hosters)
- Vertical knowledge packs we sell (Marketing Suite, etc.)
- Operational dashboards and admin tools

Everything that makes Luna work as an agent — memory, approvals, vault, plugins, channels, code, learning, cost tracking, identity, cross-agent comms — is open, is MIT, and stays that way.

---

*This document is the canonical reference for the Luna website. Every claim made here is accurate to the current state of the platform or reflects capabilities actively shipping for launch.*
