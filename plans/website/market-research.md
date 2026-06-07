# What Organizations Need From AI Agents — Market Research

> Research on market demand, buyer expectations, and the structural gaps Luna is positioned to fill.

---

## The Market in 2026

The AI agent market has crossed the tipping point. BCG estimates up to **$200 billion in net new technology services demand** driven by agentic AI over the next five years. The US AI consulting market alone reached ~$47 billion in 2026, up from $14 billion in 2023. More than 40% of large enterprises are already scaling agentic AI beyond pilots.

But the demand isn't evenly distributed. The market splits into three clear segments with different needs:

---

## Segment 1: Service Providers & Consultants

**Who they are:** AI consultants, digital agencies, freelance automation specialists, and boutique firms that implement AI solutions for their clients.

**Market size:** The fastest-growing segment. The AI consulting market grew 3.4x in three years. Hourly rates: $150–$450. Project fees: $15K–$500K+. Retainers: $5K–$15K/month.

**What they need from an agent platform:**

| Need | Why |
|------|-----|
| **White-label or neutral branding** | They sell under their own name; "powered by X" must be subtle |
| **Multi-tenant management** | Manage agents for 10, 50, 200 clients from one place |
| **Per-client isolation** | Client A's data must never touch Client B — legal liability |
| **Predictable pricing** | They quote fixed fees; per-token billing is impossible to forecast |
| **Rapid provisioning** | Set up a client's agent in minutes, not days |
| **Customizable behavior** | Each client gets different plugins, identity, permissions |
| **Self-hosting option** | Some enterprise clients demand on-premise or private cloud |
| **Cloning/templating** | "Marketing Agent" template → deploy to 30 clients |
| **Cost visibility** | Bill clients accurately; know margin per engagement |
| **Reliability** | Downtime = angry client calls at 2am |

**What's broken for them today:**

Most agent platforms are consumer-oriented (single-user, personal productivity) or developer-oriented (requires engineering to operate). There's no middle ground: a platform that a non-engineer consultant can operate but that provides the isolation, management, and reliability a professional service requires.

n8n comes closest for technical consultants but requires Docker expertise and self-hosting. Lindy is too personal-productivity focused. Claude Cowork is desktop-native, not hostable. Nobody serves the "I deploy agents for clients" workflow cleanly.

---

## Segment 2: SMB Operators & Knowledge Workers

**Who they are:** Marketing managers, operations leads, executive assistants, small business owners, content creators, recruiters — people who want an agent to do work, not a tool to build agents.

**Market size:** The largest segment by count but the most price-sensitive. Willingness to pay: $0–$50/month for clear, immediate value.

**What they need:**

| Need | Why |
|------|-----|
| **Zero-setup onboarding** | "Sign up → working agent" in under 2 minutes |
| **Natural language control** | No code, no config files, no YAML |
| **Multi-channel access** | Chat on web, follow up on WhatsApp, approve on phone |
| **Credential management** | "Connect my Google Ads" without understanding OAuth |
| **Affordable all-inclusive pricing** | One bill, predictable, no surprise LLM costs |
| **Memory that persists** | "Remember I told you about the Q4 campaign" — and it does |
| **Approval safety net** | Won't accidentally spend $10K or email the wrong person |
| **Templates for their use case** | "I want a marketing agent" → pre-configured, ready to go |
| **Mobile access** | Approve things from their phone while commuting |

**What's broken for them today:**

ChatGPT and Claude are stateless — every conversation starts fresh, no persistent memory, no credential vault, no real work done across sessions. Copilot and Cursor are developer tools. n8n and Make are workflow builders that require technical thinking. Lindy is close but shallow on agent depth (no code execution, limited self-improvement, no open-source escape hatch).

The gap: **an agent as polished as ChatGPT, as private as self-hosting, that actually does things instead of just talking.**

---

## Segment 3: Technical Teams & Developers

**Who they are:** Engineering teams, DevOps, indie hackers, open-source enthusiasts — people who want control, extensibility, and the ability to inspect, modify, and self-host.

**Market size:** Smaller by revenue per user but crucial for ecosystem health, community contributions, plugin development, and credibility.

**What they need:**

| Need | Why |
|------|-----|
| **Open source with real license** | MIT, not "source available" or AGPL with restrictions |
| **Self-hostable on their infrastructure** | Data residency, compliance, cost control |
| **Extensible plugin system** | Build custom integrations without forking |
| **Clean API surface** | Programmatic control, not just UI |
| **Small core, readable code** | Understand the system in a day, contribute meaningfully |
| **Standard stack** | Python, Postgres, Docker — not exotic dependencies |
| **Active community** | Issues get answers, PRs get reviewed, roadmap is public |
| **Escape hatch from hosted** | Start on hosted, self-host later — same agent, same data |

**What's broken for them today:**

OpenClaw (Claude Code) and NanoClaw (similar agents) have structural flaws: laptop-shaped (not cloud-native), filesystem memory (not queryable), prompt-based approvals (not enforced), no cost visibility, no self-improvement, no cross-agent communication. n8n is strong for workflows but weak as a persistent agent. Most "agent frameworks" (LangChain, CrewAI, AutoGen) are libraries, not platforms — they require building everything yourself.

---

## Cross-Segment Demand Patterns

Across all three segments, five themes emerge consistently:

### 1. Trust & Safety
The #1 concern with autonomous agents is "what if it does something wrong at scale?" Enterprises and SMBs both want **hard approval gates** — not prompt instructions, not guardrails that the LLM might ignore, but architectural enforcement. 87% of enterprise buyers cite governance as their top requirement for agent adoption (IDC, 2026).

### 2. Data Privacy
"Where does my data go?" is asked in every sales conversation. Per-tenant isolation, encrypted vaults, no cross-tenant data leakage, no telemetry of conversation content. This is table stakes for anyone putting credentials or business data into an agent.

### 3. Predictable Costs
Token-based pricing is universally disliked outside of developer circles. Business users and service providers need fixed monthly costs they can budget and bill against. The all-inclusive model (one bill, LLM usage included) is the expectation set by ChatGPT Plus, Claude Pro, and Cursor — and anything that deviates from it causes friction.

### 4. Time to Value
Whether it's a consultant setting up a client or an SMB owner trying a new tool, the tolerance for setup time is shrinking. "Under 5 minutes to useful" is the new bar. Anything requiring Postgres provisioning, Docker configuration, or API key juggling loses 80% of the addressable market.

### 5. Portability
Lock-in anxiety is real. "What happens if you shut down?" or "What if I outgrow your platform?" are asked early. The answer must be concrete: export your agent, run it on your own infrastructure, with the same code, the same data, the same capabilities. Open source makes this promise credible in a way no proprietary platform can.

---

## Market Sizing Relevant to Luna

| Segment | Addressable Market | Luna's Angle |
|---------|-------------------|-------------|
| **Hosted AI agents (consumer)** | ~$5B by 2028 (est.) | Luna Service — free tier funnels to Pro/Power |
| **AI consulting/services** | ~$47B US in 2026 | Luna as the tool consultants deploy for clients |
| **Self-hosted agent platforms** | ~$2B (developer tools) | Luna OSS — community + ecosystem + enterprise pipeline |
| **Vertical AI solutions** | ~$15B+ | Knowhow packs — Marketing Suite, Sales, Support |

Luna's unique position: the only platform that serves all three segments with a single codebase, a single architecture, and a single open-source promise.

---

## Key Takeaway for the Website

The website must speak to **buyers who are tired of demos and want to just use the thing**. The market has seen enough "build your own agent" pitches. What's scarce is:

1. An agent that works out of the box
2. That you can trust with real credentials and real money
3. That remembers you across sessions
4. That costs a predictable amount per month
5. That you can leave anytime because the code is open

Every section of the website should reinforce these five points. Features are only compelling when framed as solutions to these five problems.
