# Luna Website — Complete Plan

> The full website plan for luna.com.ai. Every page, every section, every word serves one of three ICPs: Agent Enthusiasts, AI Service Providers, or Business Operators. The website is for the launch — it must convert all three.

---

## Design Philosophy

### Visual Identity
- **Dark theme by default** — matches the existing Luna UI. Deep blacks, soft purples (#a78bfa as accent), high-contrast text. Luna's 🌙 moon motif throughout.
- **Clean, spacious, modern.** Not startup-template generic. Not developer-doc sparse. Somewhere between Linear's polish and Vercel's authority.
- **Motion is subtle.** Scroll-triggered reveals, smooth transitions. No gratuitous animation. No particle effects.
- **Typography is sharp.** System fonts or a single premium sans-serif. Large hero text, readable body. No decorative fonts.
- **Code blocks are real.** When we show code, it's actual Luna code in a beautiful syntax-highlighted block. Not fake screenshots.

### Page Story Structure (see `page-story-guidelines.md` for the full rules)

Every page tells **one story, repeated from every angle**. Users drop off at every scroll — so the story must land wherever they stop.

- **The hero tells the complete story** in its most compressed form.
- **Each section retells the story** from a different angle — every section is self-sufficient.
- **Four reading layers must all work:** (1) titles only = full story, (2) titles + subtitles = deeper story, (3) any single section = full story through one lens, (4) full page = comprehensive version.
- **Every section has exactly four elements:** title, subtitle, content, visual. No exceptions.
- **No building up to a point.** The point lands in every section, not at the end.

### Content Principles (see `copy-guidelines.md` for the full rules)
- **Lead with the reader's wish, not with Luna.** Speak to what they want before explaining how Luna delivers it.
- **"You" and "your" before "we" and "Luna."** Every headline addresses the reader, not the product.
- **Every section answers "what do I get?"** Not "what does Luna do." Outcomes, not feature descriptions.
- **Honest about what's live vs. coming.** No vaporware. If it's not shipped, label it.
- **Speak to humans AND agents.** Clear semantics so an agent evaluating Luna for a user can parse capabilities, pricing, and differentiation.

---

## Sitemap

```
luna.com.ai/
├── / ............................ Hero + Landing Page
├── /features ................... Deep feature breakdown
├── /for-providers .............. AI Service Providers page
├── /pricing .................... Pricing tiers + calculator
├── /open-source ................ OSS story + GitHub + community
├── /security ................... Security & privacy architecture
├── /docs ....................... Documentation hub (link to docs site)
├── /blog ....................... Technical blog + updates
├── /about ...................... Team, mission, company
├── /login ...................... Sign in (Google OAuth)
├── /signup ..................... Sign up (Google OAuth → provision)
└── /admin ...................... Dashboard (authenticated)
```

---

## Page-by-Page Plan

---

### Page 1: Hero / Landing Page (`/`)

**Primary ICP:** Business Operator
**Secondary ICP:** Everyone (first impression matters for all three)

#### Section 1: Hero

**Headline:** `Your work, finally compounding.`
**Subhead:** `Self-improving. Self-reflecting. Finally trustworthy.`

**Body (2 lines max):**
> Luna is an open-source AI agent that remembers everything, writes its own tools, learns from experience, and asks before it acts. One bill. Fully isolated. Yours to keep.

**CTA buttons:**
- Primary: `Sign up free` (→ Google OAuth)
- Secondary: `View on GitHub` (→ github.com/huemorgan/luna)

**Below fold hint:** Subtle scroll indicator or a preview of the next section.

**Design notes:**
- Luna moon icon/logo centered above headline
- Dark background with subtle radial gradient (purple glow from center)
- Hero takes full viewport height
- Sign-up button should feel premium — Luna purple (#a78bfa) with hover glow

#### Section 2: Stop repeating yourself.
- **Title:** "Stop repeating yourself."
- **Subtitle:** "Every conversation, every preference, every decision — remembered. Permanently."
- **Content:** You tell it once. It knows forever. Not because you re-prompted it — because your context lives in a real database, searchable and persistent. Ask about something from last month. It's there.
- **Visual:** Screenshot of a conversation where Luna recalls a fact from weeks ago without being reminded.

#### Section 3: Trust it with real work.
- **Title:** "Trust it with real work."
- **Subtitle:** "Architectural approval gates — the AI literally cannot act without your say."
- **Content:** Spend money? Send a message? Change a system? The execution engine stops and waits for you. Not a prompt instruction — a hard gate the LLM cannot bypass. You choose: yes this time, yes today, yes forever, no. Every decision logged, every standing approval revocable.
- **Visual:** Screenshot of the approval card UI with a real action description and the four-button interface.

#### Section 4: It never hits a wall.
- **Title:** "It never hits a wall."
- **Subtitle:** "Needs a new capability? It builds one. Plugins, code, tools — self-extending."
- **Content:** When Luna needs to do something it can't, it writes a plugin for itself. Scripts, websites, automations, integrations — built in a sandboxed environment, versioned, rollback-able. 20+ plugins today. More tomorrow. Some of them written by Luna itself.
- **Visual:** Screenshot of Luna generating a tool, running it, and delivering results — all within the chat.

#### Section 5: It gets better every day.
- **Title:** "It gets better every day."
- **Subtitle:** "Self-reflecting. Self-improving. Every version tracked, every change reversible."
- **Content:** Luna reviews its own work, notices what failed, and proposes fixes — to its own prompts, its own tools, its own behavior. Every self-modification is versioned. One-click rollback. It improves, but it can never break itself.
- **Visual:** Screenshot of a self-improvement proposal with accept/reject and version history.

#### Section 6: Open source. Because we mean it.
- **Title:** "Open source. Because we mean it."
- **Subtitle:** "We grew up on open tools. Luna is our way of giving back."
- **Content:** The entire agent platform is MIT licensed — memory, approvals, vault, plugins, channels, code execution. ~4,600 lines of core you can read in a day. Run it yourself or let us host it. We believe the best tools are open, and we built Luna that way from day one.
- **Visual:** GitHub repo screenshot with star count + stats bar: 4,600 LOC core, 20+ plugins, MIT licensed.

#### Section 7: Turn AI projects into a business.
- **Title:** "Turn AI projects into a business."
- **Subtitle:** "One agent per client. One dashboard. Clone, customize, deploy — at margin."
- **Content:** Service providers: create an agent per client, each physically isolated. Clone templates. See per-agent costs. When enterprise clients demand on-premise, hand them the repo. Your margin, your business.
- **Visual:** Fleet management dashboard showing multiple agents with status and cost indicators.

#### Section 8: One bill. No surprises.
- **Title:** "One bill. No surprises."
- **Subtitle:** "Hosting, storage, every LLM — included. Pick the model, we handle the rest."
- **Content:** Four tiers. Free to start. All models included — Claude, GPT, Gemini. No API keys to manage, no vendor invoices to reconcile.
- **Visual:** Pricing cards — Free ($0), Pro ($29), Power ($99), Enterprise (Custom).

#### Section 9: Final CTA
- **Title:** "Start compounding."
- **Subtitle:** "60 seconds to your first conversation. No credit card."
- **CTA:** `Sign up free` (→ Google OAuth)

---

### Page 2: Features (`/features`)

**Primary ICP:** Agent Enthusiast
**Secondary ICP:** Service Provider

**Page story:** "Every capability compounds your investment — nothing is wasted, nothing is forgotten, nothing is locked away."

**Hero:**
- **Title:** "The deeper you go, the more it gives back."
- **Subtitle:** "Every feature exists so your next interaction is better than your last."

**Feature sections (each follows title/subtitle/content/visual structure):**

#### Section 1: Your context, always there.
- **Title:** "Your context, always there."
- **Subtitle:** "Tell it once. Ask about it next month. It's there."
- **Content:** Postgres-backed memory with semantic search. Cross-session recall, preference learning, searchable history. Not a chat log — a real database of everything you've built together.
- **Visual:** Conversation screenshot showing Luna recalling context from weeks ago without being reminded.

#### Section 2: Your credentials, never exposed.
- **Title:** "Your credentials, never exposed."
- **Subtitle:** "Add an API key once. Luna uses it forever — encrypted, scoped, invisible to the LLM."
- **Content:** Per-tenant encrypted vault. Key derivation per tenant. The LLM never sees raw secrets — only uses them through tools with scoped access. You store once, it works everywhere.
- **Visual:** Diagram showing credential flow: user → encrypted vault → scoped runtime access → plugin.

#### Section 3: Your trust, enforced by architecture.
- **Title:** "Your trust, enforced by architecture."
- **Subtitle:** "Not 'it was told to ask.' The execution engine stops and waits for you."
- **Content:** The execution engine pauses at approval gates. Four options: yes once, yes today, yes forever, no. Every decision logged, every standing approval visible and revocable. The AI cannot talk its way past it.
- **Visual:** Architecture diagram showing the approval interrupt flow + screenshot of the approval card.

#### Section 4: Your needs, never out of reach.
- **Title:** "Your needs, never out of reach."
- **Subtitle:** "20+ plugins today. Luna builds new ones when it hits a wall."
- **Content:** Plugin ecosystem: web search, files, brain, cron, Slack, WhatsApp, MCP adapter for any tool. Plugin SDK for building your own. When Luna encounters something it can't do, it writes a plugin for itself.
- **Visual:** Plugin grid showing icons + names, with a "Build your own" card at the end.

#### Section 5: Your ideas, actually built.
- **Title:** "Your ideas, actually built."
- **Subtitle:** "Scripts, websites, automations — written, executed, delivered. Not just suggested."
- **Content:** Full sandboxed code execution. Python, TypeScript, shell, full websites. Iterates on errors automatically. Code is versioned, rollback-able. The gap between "I need this" and "here it is" shrinks every time.
- **Visual:** Screenshot of Luna generating a script, running it, and returning results.

#### Section 6: Your conversations, everywhere.
- **Title:** "Your conversations, everywhere."
- **Subtitle:** "Ask on Slack. Check on web. Continue on WhatsApp. Same context, always."
- **Content:** Web, Slack, WhatsApp, Telegram, email — same agent, same memory. Cross-channel context is time-windowed and automatic. Your work doesn't fragment across channels.
- **Visual:** Visual showing the same conversation flowing across three channel icons.

#### Section 7: Your agent, getting sharper.
- **Title:** "Your agent, getting sharper."
- **Subtitle:** "Learns from corrections. Proposes improvements. Every change versioned and reversible."
- **Content:** Three-layer self-improvement: reflection, pattern recognition, improvement proposals. Opt-in. Every change goes through approval. One-click rollback. It compounds — every correction makes the next interaction better.
- **Visual:** Screenshot of a self-improvement proposal with accept/reject and version history.

#### Section 8: Your costs, visible.
- **Title:** "Your costs, visible."
- **Subtitle:** "Per-conversation breakdown. Optimization suggestions. No surprises."
- **Content:** Cost tracking per action, per model, per plugin. Luna suggests cheaper models when they'll do the job. Budget-aware by design — your spend compounds value, not invoices.
- **Visual:** Screenshot of the cost breakdown panel showing per-message costs and model recommendations.

#### Section 9: Your data, portable.
- **Title:** "Your data, portable."
- **Subtitle:** "Clone it. Export it. Fork it. It's a Postgres dump — yours forever."
- **Content:** Clone agents for templates. Export everything. Fork for experimentation. Since it's all Postgres + files, moving is a database dump. No lock-in, by construction.
- **Visual:** Diagram showing clone/fork/export flow.

---

### Page 3: For Service Providers (`/for-providers`)

**Primary ICP:** AI Service Provider

**Page story:** "Your AI practice, finally repeatable — one platform, every client, compounding expertise."

**Hero:**
- **Title:** "Turn AI projects into a real business."
- **Subtitle:** "Repeatable delivery. Predictable margin. No client is a snowflake."

#### Section 1: You're babysitting, not building.
- **Title:** "You're babysitting, not building."
- **Subtitle:** "n8n here, Zapier there, custom scripts everywhere. Every client is a one-off."
- **Content:** The problem: service providers cobble together a different stack for every client. Each breaks differently. You maintain snowflakes instead of building a practice. Your expertise doesn't compound because every engagement starts from scratch.
- **Visual:** Illustration of tangled tool logos vs. a clean single dashboard.

#### Section 2: One platform you master once.
- **Title:** "One platform you master once."
- **Subtitle:** "Every new client takes 5 minutes, not 5 days. Your expertise compounds."
- **Content:** One agent per client. Each in its own microVM, database, vault. Deploy from a template, customize identity and credentials, hand it to the client. Your knowledge of the platform deepens with every engagement — and each one is faster than the last.
- **Visual:** Fleet management dashboard showing multiple agents with names, statuses, and per-agent costs.

#### Section 3: Sell isolation, not promises.
- **Title:** "Sell isolation, not promises."
- **Subtitle:** "Separate VMs, databases, and vault keys per client. Compliance you can show, not just claim."
- **Content:** Why this wins enterprise deals: physical isolation per client, audit trails, data residency. Not "we promise your data is separate" — "here's the architecture diagram, each client is a separate machine." Show it in the pitch deck.
- **Visual:** Architecture diagram — three client agents, each in its own microVM/DB/key box.

#### Section 4: Build once, deploy thirty times.
- **Title:** "Build once, deploy thirty times."
- **Subtitle:** "Clone your best agent. Customize per client. Your templates compound."
- **Content:** Set up a "Marketing Agent" template: identity, plugins, credentials, knowhow packs. Clone for each new client. Swap credentials, adjust plugin configs. Every template you build makes the next client faster.
- **Visual:** Flow diagram: Template → Clone → Customize → Live agent.

#### Section 5: Your margin, transparent.
- **Title:** "Your margin, transparent."
- **Subtitle:** "See per-agent costs. Pay $29. Charge $200. The math is yours."
- **Content:** Cost dashboard per client. All LLM usage included. No hidden fees, no surprise bills. You set the price, you keep the spread.
- **Visual:** Cost breakdown showing per-agent monthly costs with clear totals.

#### Section 6: The on-premise objection is dead.
- **Title:** "The on-premise objection is dead."
- **Subtitle:** "Client wants to self-host? Hand them the GitHub link. Same code. MIT licensed."
- **Content:** The conversation that kills most AI service deals — "What if we want to bring it in-house?" — is now your strongest moment. "Here's the repo. Same code we run for you." You keep the relationship. They get freedom. Nobody is locked in.
- **Visual:** Two paths: Hosted (you manage) → Self-hosted (they run). Same codebase.

#### Section 7: Close the risk-averse buyer.
- **Title:** "Close the risk-averse buyer."
- **Subtitle:** "Show them the approval gates. Show them the audit log. The AI can't act alone."
- **Content:** Demo pitch: show the architectural approval system, explain it's not a prompt, show the four-button interface, show the decision log. Risk-averse enterprises say yes when they see hard stops, not soft instructions.
- **Visual:** Screenshot of an approval prompt for a real action with the four-button interface.

#### Section 8: CTA
- **Title:** "Start your practice."
- **Subtitle:** "First agent is free. Volume pricing at 5+."
- **CTA:** "Start free →"

---

### Page 4: Pricing (`/pricing`)

**Primary ICP:** Business Operator
**Secondary ICP:** Service Provider

**Page story:** "Pay for value that compounds — everything included, nothing hidden, leave anytime."

**Hero:**
- **Title:** "Pay for what compounds. Nothing else."
- **Subtitle:** "Hosting, models, storage — one bill. No API keys. No vendor invoices."

#### Section 1: Pricing cards (immediate, above the fold)
- **Title:** "Start free. Scale when you're ready."
- **Subtitle:** "No credit card. Upgrade anytime, prorated. Downgrade anytime."
- **Content:** Four tier cards — Free ($0), Pro ($29), Power ($99), Enterprise (Custom). All plans include: persistent memory, approval gates, plugin ecosystem, self-improvement, web access. The more you use it, the more it learns — every plan compounds.
- **Visual:** Four clean tier cards side by side. Recommended tier highlighted.

#### Section 2: No bills to reconcile.
- **Title:** "No bills to reconcile."
- **Subtitle:** "Claude, GPT, Gemini, web search — all included. Switch models mid-sentence."
- **Content:** You never manage an API key. Luna picks the right model for the task, or you choose. Cheaper models stretch your budget; frontier models burn faster — but it's one line item. Your accountant will thank you.
- **Visual:** Icon row showing all included model logos with a "= one bill" visual.

#### Section 3: Or run it yourself. Free. Forever.
- **Title:** "Or run it yourself. Free. Forever."
- **Subtitle:** "MIT licensed. Same code, same features. Docker Compose and you're live."
- **Content:** If hosted pricing doesn't fit, self-host Luna. No crippled version. No "community edition" missing features. The exact same code we run. Your ops, your cost structure, your choice.
- **Visual:** Two-column comparison: Hosted (managed) vs. Self-hosted (free, same code).

#### Section 4: Volume pricing for providers.
- **Title:** "Scale your practice, lower your costs."
- **Subtitle:** "5+ agents: volume pricing. Each new client costs less."
- **Content:** Per-agent cost curve declining with volume.
- **Visual:** Simple chart showing cost-per-agent declining as fleet grows.

#### Section 5: FAQ
- **Content:** "What happens at my token limit?" / "Can I switch plans?" / "Do I need API keys?" / "What if I want to self-host?" — each answered in one sentence.
- **Visual:** Clean accordion or expandable FAQ cards.

---

### Page 5: Open Source (`/open-source`)

**Primary ICP:** Agent Enthusiast

**Page story:** "We believe the best tools are open — Luna is open source because AI agents are too important to be closed."

**Hero:**
- **Title:** "We believe the best tools are open."
- **Subtitle:** "Luna is an open-source project aimed as a scaffold agent platform — to allow anyone to build reliable, relatable, self-reflective, self-improving agents."

#### Section 1: What's open vs. what's proprietary.
- **Title:** "Everything that makes Luna an agent is open."
- **Subtitle:** "The hosted service adds convenience. The agent itself is fully open."
- **Content:** Two-column split: Open (MIT) — core, memory, vault, approval gates, all 20+ plugins, all channels, SDK, docs. Proprietary — control plane (signup/billing), fleet dashboard, vertical knowhow packs. Note: none of the proprietary pieces are needed to run Luna.
- **Visual:** Clear two-column comparison.

#### Section 5: Under the hood. (Architecture deep-dive)
- **Title:** "A scaffold you can build on."
- **Subtitle:** "Small core, plugin-everything architecture. Every component is swappable, every decision is auditable."
- **Content:** 6-card grid covering: pydantic-ai agent engine (structured type-safe execution, not prompt loops), Postgres as the brain (everything queryable, pgvector for semantic search), Plugin-everything (~4,600 LOC core, rest is plugins with swappable interfaces), Hard approval gates (hard interrupts, scoped decisions in DB), Per-tenant isolation (separate schema, encryption key, filesystem), Event bus not imports (crash-isolated plugins, own DB namespace, egress allowlists).
- **Visual:** Architecture card grid.

#### Section 6: Standard tools. No surprises.
- **Title:** "Standard tools. No surprises."
- **Subtitle:** "Python 3.12+ · pydantic-ai · FastAPI · PostgreSQL + pgvector · React + Vite · Docker"
- **Content:** Standard stack. No exotic dependencies. Clone, read, run — three commands.
- **Visual:** Code block with git clone / cd luna / docker compose up.

#### Section 7: Build with us.
- **Title:** "Build with us."
- **Subtitle:** "Contribute to core. Build plugins. Help others self-host."
- **Content:** Plugin SDK, MCP adapter, community guidelines. Every contribution compounds the platform.
- **Visual:** Plugin SDK + community links.

#### Section 8: CTA
- **Title:** "Read it. Run it. Build on it."
- **Subtitle:** "The code is there. The community is growing. Come build with us."
- **CTA:** Two buttons — "Star on GitHub" / "Read the docs"

---

### Page 6: Security & Privacy (`/security`)

**Primary ICP:** Service Provider
**Secondary ICP:** Business Operator

**Page story:** "You shouldn't have to trust us. The architecture makes it so you don't have to."

**Hero:**
- **Title:** "You don't have to trust us. The architecture handles it."
- **Subtitle:** "Physical isolation. Per-tenant encryption. Zero conversation telemetry."

#### Section 1: Your agent is physically yours.
- **Title:** "Your agent is physically yours."
- **Subtitle:** "Own microVM. Own database. Own encryption key. Not shared. Not 'logically separated.'"
- **Content:** Every agent runs in a separate Fly Machine. An exploit in one agent cannot reach another — not because of access controls, but because there's no shared process to exploit. This is what you tell your compliance team.
- **Visual:** Architecture diagram showing three agents in separate VM/DB/key boxes. Contrast with a "shared process" diagram.

#### Section 2: We literally can't read your secrets.
- **Title:** "We literally can't read your secrets."
- **Subtitle:** "Per-tenant vault keys. Decrypted only in your agent's runtime memory. Never on disk."
- **Content:** Master key derives per-tenant keys. We (the operator) cannot decrypt your credentials. The raw secret exists only in runtime memory — never logged, never stored unencrypted. This isn't a policy. It's cryptography.
- **Visual:** Encryption flow diagram: user → encrypted vault → scoped runtime access → agent memory.

#### Section 3: Your conversations are yours alone.
- **Title:** "Your conversations are yours alone."
- **Subtitle:** "We track uptime and error rates. We never see your messages, files, or credentials."
- **Content:** No conversation logging. No content analysis. No training on your data. Support impersonation requires your explicit consent and is fully audit-logged. Two-column proof: what we see vs. what we never see.
- **Visual:** Two-column split: "What we see" (uptime, errors, costs) vs. "What we never see" (messages, files, vault contents).

#### Section 4: Your compliance team will be happy.
- **Title:** "Your compliance team will be happy."
- **Subtitle:** "SOC 2 control plane. Encrypted transit. HttpOnly sessions. GDPR by architecture."
- **Content:** Render.com (SOC 2) for control plane. Fly.io for compute. Cloudflare R2 for storage. HttpOnly + Secure + SameSite cookies, server-side sessions, no JWT in localStorage. SOC 2 in progress. GDPR compliant by construction (per-tenant data, deletion on request). Enterprise: custom data residency.
- **Visual:** Infrastructure diagram showing the security stack with trust boundaries labeled.

---

### Page 7: Blog (`/blog`)

Technical blog for credibility and SEO. Every post answers a reader's question — not "look what we built."

Launch posts:

1. **"Why your AI forgets you (and what to do about it)"** — The memory problem. Why Postgres, not files. Why persistence compounds.
2. **"The AI trust problem isn't prompts — it's architecture"** — Why prompt-based approvals fail. How Luna's approval gates actually work.
3. **"4,600 lines: why a small core matters for AI agents"** — Plugin architecture. Why extensibility beats monoliths. Why your agent should grow, not bloat.
4. **"We built Luna because we needed it"** — Origin story. The gap. Why open source. Why this architecture.
5. **"What scale-to-zero means for your AI bill"** — Fly Machines suspend/resume. Idle agents cost nothing. What this enables.
6. **"One bill vs. BYOK: why we include all models"** — The business decision. Why managing API keys is friction that kills compounding.

---

### Page 8: About (`/about`)

- Team (when ready to be public)
- Mission: "AI that compounds your work — persistent, trustworthy, yours."
- Company: Novalystrix (the entity behind Luna)
- Contact

---

## Navigation

**Desktop navbar:**
```
[🌙 Luna]  Features  For Providers  Pricing  Open Source  Docs  Blog  [Sign in]  [Sign up free]
```

**Mobile:** Hamburger menu with same items. Sign up button always visible.

**Footer:**
```
Product: Features | Pricing | Security | Docs
Open Source: GitHub | Contributing | Plugin SDK | Community
Company: About | Blog | Contact | Privacy Policy | Terms
```

---

## SEO Strategy

**Primary keywords:**
- "AI agent platform"
- "open source AI agent"
- "hosted AI agent"
- "AI agent for business"
- "deploy AI agents for clients"

**Blog-driven SEO:**
- Technical posts targeting developer queries ("postgres vs files for AI memory", "AI agent approval system architecture")
- Use case posts targeting business queries ("AI marketing agent", "AI operations agent")
- Comparison posts ("Luna vs n8n", "Luna vs Lindy", "Luna vs Claude Cowork")

**Technical SEO:**
- Clean URLs, fast load times (static-first, no heavy frameworks)
- Structured data (Organization, Product, FAQ schemas)
- OpenGraph and Twitter cards for social sharing
- Sitemap.xml, robots.txt

---

## Launch Sequence

### Pre-Launch (2 weeks before)
1. GitHub README polished with architecture diagram and quick start
2. Landing page live with waitlist (email capture)
3. Technical blog post #1 published ("Why We Built Luna")
4. Product Hunt draft prepared
5. Hacker News "Show HN" post drafted

### Launch Day
1. Remove waitlist, enable sign-up
2. Publish Product Hunt listing
3. Post "Show HN: Luna — open-source AI agent platform" on Hacker News
4. Tweet thread from founder account with demo video
5. Cross-post to Reddit (r/selfhosted, r/ChatGPT, r/LocalLLaMA, r/SideProject)
6. Email waitlist

### Post-Launch (weeks 1–4)
1. Publish blog posts #2–#6 on a weekly cadence
2. Engage with every GitHub issue and community post
3. Create and publish Plugin SDK documentation
4. Write comparison posts (vs n8n, vs Lindy)
5. Reach out to AI newsletter curators (TLDR AI, Ben's Bites, The Rundown)
6. Launch Discord community

---

## Technical Implementation

**Stack:** The website is part of the Luna Service control plane — React (Vite), served from the same Render deployment.

**Existing pages to revamp:**
- Current landing page at `/` — replace entirely with the new hero design
- Current sign-in flow — keep, but style to match new design

**New pages to build:**
- `/features` — static content page
- `/for-providers` — static content page
- `/pricing` — static with live GitHub star counter
- `/open-source` — static with live GitHub stats (star count, contributors)
- `/security` — static content page
- `/blog` — consider headless CMS or static markdown rendering

**Performance targets:**
- First Contentful Paint: < 1.5s
- Largest Contentful Paint: < 2.5s
- Cumulative Layout Shift: < 0.1
- Total page weight: < 500KB (excluding images)

**Analytics:** Plausible (privacy-friendly) or PostHog (product analytics). No Google Analytics.

---

## Success Metrics

| Metric | Target (Month 1) | Target (Month 3) |
|--------|-------------------|-------------------|
| Website visitors | 10,000 | 50,000 |
| Sign-ups (free) | 500 | 3,000 |
| GitHub stars | 1,000 | 5,000 |
| Paid conversions | 50 | 300 |
| Blog post views | 5,000 | 25,000 |
| Hacker News upvotes | 100+ | — |
| Product Hunt upvotes | 200+ | — |

---

## What the Website Must Feel Like

When someone lands on luna.com.ai, they should feel three things in order:

1. **"This is what I've been looking for."** — The headline speaks to their frustration. They feel seen before they see a feature.
2. **"This is real."** — Screenshots, architecture diagrams, actual code. Not illustrations of people smiling at laptops. Not vaporware.
3. **"I need to try this."** — The CTA is clear, signup is 60 seconds, the free tier holds nothing back, and the first conversation proves the work compounds.

The website doesn't convince people to want an AI agent. Everyone already wants one. The website convinces them that **this one actually follows through** — and gets better the more they use it.

---

*Reference docs:*
- `plans/website/luna-product-bible.md` — canonical feature and capability reference
- `plans/website/market-research.md` — what the market needs
- `plans/website/competitors.md` — competitive positioning
- `plans/website/icp-profiles.md` — who we're building for
