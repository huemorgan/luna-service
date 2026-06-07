# Ideal Customer Profiles (ICPs)

> Detailed profiles of the people who will use Luna, what drives them, what scares them, and what makes them buy.

---

## ICP Overview

Three primary ICPs, ordered by **revenue potential** (not volume):

1. **The AI Service Provider** — deploys agents for clients (highest LTV)
2. **The Agent Enthusiast** — power user, early adopter, community builder (highest influence)
3. **The Business Operator** — wants an agent to do their job, not a hobby (largest volume)

---

## ICP 1: The AI Service Provider

### Profile

| Attribute | Details |
|-----------|---------|
| **Title** | AI Consultant, Automation Specialist, Digital Agency Owner, Fractional CTO |
| **Company** | Solo consultant or boutique firm (2–20 people). Some at larger agencies. |
| **Revenue** | $100K–$2M/year. Charges $150–$400/hour or $15K–$200K per project. |
| **Technical skill** | Medium-high. Can operate Docker, APIs, cloud platforms. Not a full-stack engineer but technically literate. |
| **Age/demo** | 28–50. Predominantly male. US, UK, Western Europe, Israel, India, Australia. |
| **Archetype** | "I solve companies' AI problems. I need a platform I can deploy and manage for my clients." |

### Day in Their Life

They juggle 5–15 active clients. Each client wants "AI that does X" — answers support tickets, qualifies leads, manages social media, automates reporting. Today they cobble together solutions from n8n, custom scripts, Zapier, and prompt engineering. Every client is a bespoke build. They spend more time on infrastructure than on the actual AI logic.

They bill for outcomes but spend half their time on plumbing. They're drowning in maintenance — updating API keys, monitoring uptime, debugging workflow failures, explaining to clients why the bot said something wrong.

### What They Want From Luna

1. **One platform to deploy for all clients.** Not n8n for this client, Zapier for that one, custom code for the third.
2. **Per-client isolation.** Client A's data must never touch Client B's. They need this for contracts and liability.
3. **Templates and cloning.** Build a "Marketing Agent" once, clone it for 30 clients with custom configurations.
4. **Predictable costs they can mark up.** Pay $29/agent/month, charge the client $200/month. Clean margin.
5. **Management dashboard.** See all agents, all clients, all costs in one view.
6. **Self-hosting option for enterprise clients.** Some clients demand on-premise. Luna OSS makes this possible.
7. **Approval system they can show clients.** "Your agent will never spend money or send emails without your approval" — this closes deals.

### What Scares Them

- **Vendor lock-in.** They've been burned by platforms that changed pricing, limited features, or shut down. Open source is a trust signal.
- **Reliability.** Downtime = angry client calls. They need SLAs or at least proven uptime.
- **Hidden costs.** Per-token pricing is impossible to forecast when quoting a fixed project fee.
- **Client data exposure.** If one client's data leaks to another, their business is over.

### How Luna Converts Them

- **Landing page:** "Deploy AI agents for your clients. Per-client isolation. One dashboard. Open source."
- **Proof point:** Show the fleet management dashboard. Show per-agent cost breakdown. Show the cloning workflow.
- **Pricing:** Per-agent pricing with volume discounts. Clear margin opportunity.
- **Trust:** MIT license, self-hosting option, architectural isolation diagram.
- **CTA:** "Start free → Deploy your first client agent in 5 minutes"

### Revenue Model

- **Average agents per provider:** 10–50
- **Average tier:** Pro ($29/agent) or Power ($99/agent)
- **Monthly revenue per provider:** $290–$4,950
- **Annual LTV:** $3,500–$60,000
- **Churn risk:** Low (switching costs are high once agents are deployed for clients)

---

## ICP 2: The Agent Enthusiast

### Profile

| Attribute | Details |
|-----------|---------|
| **Title** | Developer, Indie Hacker, AI Tinkerer, Technical Content Creator, Open Source Contributor |
| **Company** | Self-employed, startup employee, or works at a tech company but builds agent projects on the side |
| **Revenue** | Variable. Some make $0 (hobbyists), some make $200K+ (senior devs/founders). |
| **Technical skill** | High. Comfortable with Python, Docker, Postgres, APIs. Many contribute to open source. |
| **Age/demo** | 22–40. Global. Active on Twitter/X, Hacker News, Reddit, Discord, GitHub. |
| **Archetype** | "I want to build the future. I evaluate every agent platform. I tell 10,000 people what I think." |

### Day in Their Life

They follow every AI launch. They've tried Claude Code, Cursor, n8n, CrewAI, AutoGen, LangChain, and a dozen others. They evaluate tools deeply — reading source code, checking architecture decisions, testing edge cases. They blog, tweet, and create YouTube videos about what works and what doesn't.

They want an agent they can **understand, modify, and own**. They distrust proprietary platforms. They respect clean architecture. They contribute to projects they believe in.

### What They Want From Luna

1. **MIT license, truly open.** Not "source available" with AGPL restrictions. Not "open core" with crippled free tiers.
2. **Small, readable codebase.** ~4,600 lines of core. They can understand the system in a day.
3. **Plugin SDK.** Build custom plugins without forking. `luna plugin init` scaffolding.
4. **Standard stack.** Python, Postgres, Docker. No exotic dependencies.
5. **Self-hostable on a $5 VPS.** Not just theoretically — actually works on minimal hardware.
6. **Clean architecture decisions.** pydantic-ai for execution, Postgres for state, event bus for plugin communication — decisions they respect.
7. **Active community.** Issues get answered. PRs get reviewed. Roadmap is public.
8. **Ability to contribute.** Not just use it — shape it. Plugin contributions, core improvements, documentation.

### What Scares Them

- **Rug-pull risk.** "What if you relicense?" → MIT is the answer. Binds acquirers.
- **Bloat.** They don't want a 50K LOC monolith. They want small core + plugins.
- **Corporate capture.** They want the OSS to be real, not a marketing funnel with artificial limits.
- **Stale maintenance.** They check commit frequency, issue response time, PR merge rate.

### How Luna Converts Them

- **GitHub README:** Architecture diagram, quick start, "understand the core in a day."
- **Website:** Technical deep-dive page. Not marketing fluff — real architecture docs.
- **Community:** Discord/GitHub Discussions with active maintainers.
- **Content:** Technical blog posts about design decisions. "Why Postgres over files for agent memory." "Why architectural approvals, not prompt instructions."
- **CTA:** "Star on GitHub → Try self-hosting → Join the community"

### Revenue Model

- **Direct revenue:** Low initially. Many use OSS for free.
- **Indirect revenue:** Enormous.
  - They write blog posts and tweets that drive awareness (10,000+ followers each)
  - They build plugins that make Luna more valuable
  - They file bug reports that improve quality
  - They become service providers (ICP 1) who deploy Luna for clients
  - They recommend Luna to non-technical friends (ICP 3)
  - They eventually convert to Luna Service for convenience ("I know I can self-host, but $29/mo is easier")
- **GitHub stars → Hacker News front page → Product Hunt → mainstream press pipeline.** This ICP is the engine.

---

## ICP 3: The Business Operator

### Profile

| Attribute | Details |
|-----------|---------|
| **Title** | Marketing Manager, Operations Lead, Small Business Owner, Content Creator, Executive Assistant, Recruiter, Freelancer |
| **Company** | SMB (1–100 employees) or solo operator |
| **Revenue** | $50K–$500K/year (personal) or company revenue $200K–$20M |
| **Technical skill** | Low-medium. Comfortable with SaaS products. Cannot and will not use Docker, APIs, or command lines. |
| **Age/demo** | 25–55. Skews slightly female for ops/admin roles. Global but English-speaking markets first. |
| **Archetype** | "I want an AI that does my job. Not a tool to build AI. Not a project. A teammate." |

### Day in Their Life

They're overwhelmed. Too many tasks, not enough time. They've tried ChatGPT — it's helpful but forgets everything. They've tried Zapier — it automates specific tasks but doesn't think. They want something in between: an intelligent entity that knows their business, remembers their preferences, and handles recurring work autonomously.

They don't want to learn a platform. They want to talk to an agent like they'd talk to an assistant: "Check my Google Ads performance this week and tell me if anything looks off." "Draft a response to this client email." "Remember that our Q4 budget is $50K."

### What They Want From Luna

1. **Zero-setup onboarding.** Sign up with Google → working agent in 60 seconds.
2. **Natural language everything.** Tell Luna what to do in English. No code, no config files.
3. **Memory across sessions.** "I told you about this last week" — and Luna remembers.
4. **Credential management without complexity.** "Connect my Google Ads" → OAuth flow → done. No API keys, no developer console.
5. **Affordable, predictable pricing.** One bill, includes everything. $0–$29/month.
6. **Approval safety net.** Won't accidentally spend $10K or email the CEO something embarrassing.
7. **Templates.** "I want a marketing agent" → pre-configured, ready to go.
8. **Mobile access.** Approve things from their phone. Chat on the commute.
9. **Multiple channels.** Start in web chat, follow up on WhatsApp, get notified on email.

### What Scares Them

- **Complexity.** Any hint of "developer tool" or "technical setup" and they bounce.
- **AI doing something wrong.** "What if it sends the wrong email?" → Approvals.
- **Unpredictable costs.** "Am I going to get a $500 bill?" → All-inclusive pricing.
- **Privacy.** "Who can see my conversations?" → Per-tenant isolation, encrypted vault, no telemetry.
- **Commitment.** "What if I don't like it?" → Free tier, no lock-in, export anytime.

### How Luna Converts Them

- **Landing page:** "Your own AI agent. In the cloud. In under a minute."
- **Hero demo:** Show a 60-second signup → first conversation → Luna remembers something → Luna checks Google Ads → Luna asks for approval before acting.
- **Social proof:** "10,000+ agents running" / testimonials from people like them.
- **Pricing:** Free tier prominently displayed. Pro tier with clear value proposition.
- **CTA:** "Sign up free → Talk to your Luna in 60 seconds"

### Revenue Model

- **Conversion path:** Free → Pro ($29/mo) after hitting token limits or wanting always-on triggers
- **Average time to convert:** 2–4 weeks of free usage
- **Monthly revenue per user:** $29 (Pro)
- **Annual LTV:** $250–$350 (some churn, some upgrade to Power)
- **Volume:** Largest ICP by count. Target: 10,000+ free users, 1,000+ paid in year one.

---

## ICP Priority for Website

| Priority | ICP | Why |
|----------|-----|-----|
| **1** | Agent Enthusiast | They drive awareness, community, and credibility. Without them, nobody knows Luna exists. The website must earn their respect. |
| **2** | AI Service Provider | Highest revenue per customer. The website must show fleet management, isolation, and margin opportunity. |
| **3** | Business Operator | Largest volume. The website must make signup feel effortless and safe. They convert after the enthusiasts and providers have validated the platform. |

### Website Section Mapping

| Website Section | Primary ICP | Secondary ICP |
|----------------|------------|---------------|
| Hero / Landing | Business Operator | Everyone |
| How It Works | Business Operator | Service Provider |
| Features Deep Dive | Agent Enthusiast | Service Provider |
| Architecture / Tech | Agent Enthusiast | — |
| For Service Providers | Service Provider | — |
| Pricing | Business Operator | Service Provider |
| Open Source / GitHub | Agent Enthusiast | — |
| Use Cases / Templates | Business Operator | Service Provider |
| Security & Privacy | Service Provider | Business Operator |
| Docs / API | Agent Enthusiast | Service Provider |

---

## Conversion Funnels by ICP

### Agent Enthusiast
```
Hacker News / Twitter / Reddit
  → GitHub README (stars)
  → Self-host locally (try it)
  → Blog post / tweet about it (amplify)
  → Recommend to non-technical friend (ICP 3 acquisition)
  → Eventually sign up for Luna Service for convenience
```

### AI Service Provider
```
Google search "AI agent platform for clients"
  → Website "For Service Providers" page
  → Sign up free, create test agent
  → Deploy for first client (Pro tier)
  → Scale to 10+ client agents
  → Volume pricing conversation
```

### Business Operator
```
Heard about Luna (friend, tweet, blog, ad)
  → Website hero ("Your own AI agent in 60 seconds")
  → Sign up free, first conversation
  → Hit token limit or want triggers
  → Upgrade to Pro ($29/mo)
  → Tell colleagues (word of mouth)
```

---

## Key Insight

**The Agent Enthusiast is the ignition.** They create the content, the GitHub stars, the Hacker News posts, the Twitter threads that make the other two ICPs discover Luna. The website must serve all three, but if it doesn't earn the enthusiast's respect first, the other two never arrive.

The enthusiast cares about architecture, honesty, and openness. The service provider cares about margin, isolation, and reliability. The business operator cares about simplicity, safety, and cost. The website must speak all three languages without compromising any of them.
