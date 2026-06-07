# Competitive Landscape

> Every platform Luna competes with, what they're good at, what they're not, and where Luna fits.

---

## The Competitive Map

Luna sits at the intersection of four categories that most competitors only occupy one of:

```
                    HOSTED / MANAGED
                         │
            Lindy ────── │ ──── ChatGPT/Claude
            Relevance AI │     (stateless chat)
                         │
  WORKFLOW ──────────────┼──────────────── AGENT
  BUILDER                │              (persistent,
  (n8n, Make,           │               autonomous)
   Zapier)              │
                         │
            CrewAI ───── │ ──── Luna OSS
            AutoGen      │     OpenClaw/NanoClaw
                         │
                    SELF-HOSTED / OSS
```

Luna is the only platform that is **both** a persistent autonomous agent **and** available as a hosted managed service **and** fully open-source self-hostable. Everyone else compromises on at least one of these three.

---

## Competitor Deep Dives

### 1. ChatGPT / Claude.ai (Anthropic)

**What they are:** Consumer AI chat products with growing agentic capabilities. ChatGPT has Operator (browser automation) and Workspace Agents. Claude has Cowork (desktop agent) and Claude Code (terminal agent).

**What they're good at:**
- Massive brand recognition and user trust
- Best-in-class model quality (GPT-5.5, Claude Opus 4.7)
- Polished UX — billions invested in consumer experience
- Broad capabilities (vision, code, analysis, writing)
- ChatGPT Plus/Pro pricing ($20–$200/mo) sets market expectations

**What they're not good at:**
- **No persistence between sessions.** Every conversation starts fresh. No long-term memory, no vault, no "remember this forever."
- **No real agent behavior.** They respond to prompts. They don't do work autonomously, don't run on a schedule, don't wake up and check your ads at 6am.
- **No per-user isolation.** Your data trains models (opt-out available but trust is eroded). No per-tenant encryption, no vault.
- **No plugin extensibility.** You get what they ship. Can't install a custom MCP server, can't add domain-specific knowhow packs.
- **No self-hosting option.** Data goes to OpenAI/Anthropic servers. Period.
- **Desktop-native (Cowork) means no cloud persistence.** Cowork runs in a sandbox on your Mac. Close the app, the agent stops. Not a persistent cloud worker.

**Luna's advantage:** Luna is what these products would be if they were persistent, private, extensible, open-source, and actually did work autonomously. Same model quality (Luna uses Claude and GPT under the hood), fundamentally different architecture.

---

### 2. n8n

**What it is:** Open-source (fair-code) workflow automation platform. Visual node-based workflow builder with 400+ integrations. Self-hostable. 170K+ GitHub stars.

**What it's good at:**
- Massive integration library (400+ connectors)
- Visual workflow builder — non-developers can understand flow
- Self-hostable with full control
- LangChain AI agent nodes — can embed LLM reasoning into workflows
- Strong developer community
- Proven at scale for enterprise automation

**What it's not good at:**
- **Not an agent.** n8n automates workflows. It doesn't remember you, doesn't have a personality, doesn't learn from experience, doesn't hold a conversation.
- **No persistent memory.** Each workflow run is stateless. No cross-session context.
- **No approval gates.** Workflows run to completion. There's no "pause and ask the human" architecture.
- **No credential vault with per-user encryption.** Credentials are stored, but not with the per-tenant isolation model Luna uses.
- **Requires technical setup.** Self-hosting means Docker, databases, monitoring. Cloud version is easier but limits control.
- **No natural language interface.** You build workflows visually or in code. You don't talk to n8n.
- **No identity or personality.** It's a tool, not an entity. It doesn't know who you are.

**Luna's advantage:** Luna is an agent that can automate workflows. n8n is a workflow engine that can call LLMs. Luna remembers, learns, talks, approves, and persists. n8n executes pipelines. Complementary for technical users (Luna can trigger n8n workflows via MCP); competitive for the "I want an AI that does my job" use case.

---

### 3. Lindy.ai

**What it is:** No-code AI agent builder for personal and small-team productivity. 3,000+ integrations. Natural language setup. Pre-built "AI employees."

**What it's good at:**
- Fastest time-to-value for non-technical users
- Natural language agent creation ("every time a new lead fills the form, enrich them")
- Pre-built templates for common use cases (inbox management, scheduling, lead routing)
- Human-in-the-loop approval flows
- Long-term memory across conversations
- Voice and text agents

**What it's not good at:**
- **Closed source.** No self-hosting option. Your data lives on Lindy's servers.
- **No code execution.** Can't write scripts, build apps, or extend itself.
- **Shallow agent depth.** Good at task-level automation, weak at multi-step reasoning, complex analysis, or self-improvement.
- **No plugin ecosystem.** You get what Lindy ships. Can't install custom plugins or connect custom MCP servers.
- **Limited enterprise governance.** No per-tenant isolation at the infrastructure level, no encrypted vault with tenant-scoped keys.
- **No open-source community.** No contribution path, no transparency into how it works.
- **Pricing can get expensive.** $199/mo for the full plan. Per-action pricing on some tiers makes costs unpredictable.

**Luna's advantage:** Luna goes deeper — code execution, self-improvement, plugin extensibility, cross-agent communication, open source with self-hosting option. Lindy is a better "quick task automator." Luna is a better "persistent intelligent teammate." For service providers deploying to clients, Luna's isolation model and self-hosting option are decisive.

---

### 4. Relevance AI

**What it is:** No-code platform for building AI "workforces" — teams of specialized agents that collaborate. Strong in GTM, operations, and research workflows.

**What it's good at:**
- Multi-agent orchestration (agents delegate to other agents)
- Role-based agent templates (research agent, SDR agent, content agent)
- Strong memory tooling for long-running tasks
- Vector search and prompt orchestration built in
- Good for multi-touch workflows (recruiting loops, outbound campaigns)
- AWS integration for enterprise governance

**What it's not good at:**
- **Credit-based pricing.** Complex, hard to predict, hard for consultants to quote.
- **No self-hosting.** Cloud-only, vendor-locked.
- **Limited for long/complex workflows.** Multi-step sequential processes hit limitations.
- **No code execution.** Agents can call tools but can't write and run code.
- **No open source.** No transparency, no escape hatch.
- **Agent depth is template-based.** Agents follow predefined patterns; they don't learn, self-improve, or build new capabilities.

**Luna's advantage:** Luna's single-agent depth (memory, vault, code, self-improvement, learning) exceeds what Relevance achieves across multiple agents. Cross-agent communication in Luna is peer-to-peer with owner consent; Relevance's multi-agent model is orchestrator-driven. For the "workforce" use case, Relevance has more pre-built templates; for the "deep persistent agent" use case, Luna wins.

---

### 5. Claude Code / Claude Cowork

**What they are:** Anthropic's agentic products. Claude Code is a terminal-native coding agent. Cowork is a desktop agent that works with your local files and applications via a sandboxed VM.

**What they're good at:**
- **Claude Code:** Elite coding agent. Terminal-first, large context, multi-file edits, git workflows.
- **Cowork:** Desktop automation — local file access, multi-step execution, plugin ecosystem, scheduled tasks.
- Best model quality for coding and reasoning (Claude Opus 4.7).
- Cowork's sandboxed VM approach is clever — real filesystem access with isolation.

**What they're not good at:**
- **Desktop-native, not cloud-native.** Cowork runs on your Mac/Windows. Close the app, the agent stops. Not a persistent cloud worker that runs 24/7.
- **No multi-tenant hosting.** Can't deploy for clients. Can't run 50 agents for 50 users.
- **No cross-session persistence at the platform level.** Each session is scoped to a task. No persistent memory across months of use.
- **No credential vault with per-user encryption.** Files are accessible but there's no structured, encrypted credential store.
- **No self-hosting of the platform.** You use Anthropic's product or nothing.
- **Coding-focused (Code) or desktop-focused (Cowork).** Neither is a general-purpose persistent agent for business operations.

**Luna's advantage:** Luna is what you'd get if Claude Cowork ran permanently in the cloud, remembered everything across sessions, had an encrypted vault, approval gates, plugin extensibility, and could be self-hosted. Luna uses Claude models for reasoning but provides the platform layer that makes an agent actually useful for persistent work.

---

### 6. OpenAI Codex / Operator

**What they are:** OpenAI's agent platforms. Codex spans an app, CLI, IDE extensions, and cloud agents. Operator is a browser automation agent.

**What they're good at:**
- **Codex:** Multi-surface engineering platform. GPT-5.5 is strong for agentic coding.
- **Operator:** Browser automation — navigates web pages, fills forms, handles multi-step web tasks.
- Massive model quality investment.
- Workspace Agents for ChatGPT business customers.

**What they're not good at:**
- **Operator's 87% success rate** means 13% of tasks fail. Not reliable enough for production business workflows.
- **No self-hosting.** Everything runs on OpenAI's infrastructure.
- **No persistent memory across conversations.** Each Codex task is ephemeral.
- **No credential vault.** No structured secret management.
- **No open source.** Fully proprietary.
- **Engineering-focused.** Not designed for marketing, ops, support, or general business use.

**Luna's advantage:** Luna is a general-purpose persistent agent, not a coding tool or browser automator. Luna's browser automation (via MCP) complements its other capabilities. Luna's approval system provides the safety net that Operator's 87% success rate can't.

---

### 7. CrewAI / AutoGen / LangChain Agents

**What they are:** Open-source agent frameworks for developers. Libraries, not platforms.

**What they're good at:**
- Maximum flexibility for developers
- Multi-agent orchestration patterns
- Large communities and ecosystem
- Good for building custom solutions from scratch

**What they're not good at:**
- **Frameworks, not products.** You get building blocks, not a working agent. You still need to build the UI, memory, vault, approvals, hosting, billing, updates.
- **No hosted option.** You build, deploy, and maintain everything yourself.
- **No persistence layer.** Memory, vault, cost tracking — build it yourself.
- **No approval system.** Build it yourself.
- **No UI.** Build it yourself.
- **High maintenance burden.** Every upgrade, every security patch, every scaling challenge is yours.

**Luna's advantage:** Luna is what you'd build if you took CrewAI/LangChain and spent 18 months turning it into a complete product. Luna uses pydantic-ai under the hood but delivers a finished, deployable, hostable agent with memory, vault, approvals, plugins, UI, and everything else already built.

---

### 8. Make / Zapier

**What they are:** Visual workflow automation platforms. The incumbents of "connect this to that."

**What they're good at:**
- Thousands of integrations (Zapier: 7,000+)
- Proven reliability at massive scale
- Non-technical user base
- Strong trigger/action model
- Zapier now has AI Agents in beta + MCP support

**What they're not good at:**
- **Not agents.** Automations, not entities. They don't remember, don't learn, don't converse.
- **Per-action pricing.** Gets expensive fast for high-volume workflows.
- **No LLM-native reasoning.** AI features are bolted on, not core.
- **No self-hosting.** Cloud-only.
- **No code execution.** Workflow steps, not general-purpose computing.
- **No personality or identity.** Tools, not teammates.

**Luna's advantage:** Luna subsumes what Zapier does (connect things, trigger actions) but adds agent intelligence (reason about what to do, remember context, ask before acting, learn from outcomes). For simple "if this then that," Zapier is fine. For "figure out what needs to happen and do it," Luna wins.

---

## Competitive Summary Matrix

| Capability | Luna | ChatGPT/Claude | n8n | Lindy | Relevance AI | CrewAI |
|-----------|------|----------------|-----|-------|-------------|--------|
| Persistent memory | **Yes** | No | No | Partial | Partial | No |
| Encrypted vault | **Yes** | No | Basic | No | No | No |
| Hard approval gates | **Yes** | No | No | Partial | No | No |
| Code execution | **Yes** | Limited | No | No | No | Via code |
| Self-improvement | **Yes** | No | No | No | No | No |
| Plugin ecosystem | **Yes** | Limited | Yes (nodes) | Limited | Limited | Via code |
| Multi-channel | **Yes** | No | Webhook | Limited | No | No |
| Cross-agent comms | **Yes** | No | No | No | Yes | Yes |
| Open source (MIT) | **Yes** | No | Fair-code | No | No | Yes |
| Self-hostable | **Yes** | No | Yes | No | No | Yes |
| Hosted/managed | **Yes** | Yes | Yes (paid) | Yes | Yes | No |
| Per-tenant isolation | **Yes (VM)** | No | N/A | No | No | N/A |
| Natural language setup | **Yes** | Yes | No | Yes | Partial | No |
| All-inclusive pricing | **Yes** | Yes | Yes | Yes | No (credits) | N/A |
| Cost visibility | **Yes** | No | No | No | Partial | No |
| Knowhow packs | **Yes** | No | No | No | Templates | No |
| Mobile access | **Coming** | Yes | No | Limited | No | No |

---

## Luna's Positioning Statement

> Luna is the only AI agent that combines the persistence of a real teammate, the safety of architecturally enforced approvals, the transparency of full cost visibility, the extensibility of a plugin ecosystem, the trust of open-source MIT licensing, and the convenience of a managed cloud service — all in one platform that service providers can deploy for clients, developers can self-host, and non-technical users can sign up for in 60 seconds.

No competitor hits all six: persistent, safe, transparent, extensible, open, and convenient. That's the gap Luna fills.
