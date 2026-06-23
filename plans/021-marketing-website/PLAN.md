# 021 — Marketing website (luna.com.ai public site)

> A full public website for Luna, served at the root of `luna.com.ai`. It sells
> **Luna Hosting Service** first, while honestly promoting **Luna Open Source**
> and explaining **Luna Marketplaces**. One job above all: turn a visitor into a
> signed-up user. Voice: reliable, trustworthy, built for people who need agents
> that do **real work**.

## Context

`luna.com.ai/` today renders a thin `Landing` page (`cloud/ui/src/pages/Landing.tsx`)
inside the control-plane SPA. The vision always called for a real **"Marketing
site (luna.com.ai)"** on the control plane (`vision/vision.md` § High-Level
Architecture) — it was just never built. We now have a strong story to tell:

- The **deck** (`Untitled presentation.pdf`) frames Luna as the **second
  generation** of self-reflective / self-improving (SR-SI) agents. First-gen
  "Claw-style" agents (OpenHands/Claude-Code-style) show the promise but **break,
  run inconsistently, and aren't secure**. Luna's thesis: keep SR-SI, but make it
  **Reliable** and **Trustworthy** — fit to own business-critical work.
- The **vision** gives the commercial spine: 60-second signup, physical
  isolation, **one bill / no BYOK / pick any model**, always-on triggers, a fleet
  dashboard, "we never look at your data," Free/Pro/Power/Enterprise.

This plan turns that into a website. It is a **luna-service** plan (the marketing
site is control-plane, public, unauthenticated) — no Luna submodule change.

## Audience & positioning

**Primary audience:** people who need a **dependable agent doing actual work** —
forward-deployed engineers, ops/RevOps/infra folks, technical founders, anyone
who has been burned by flaky "autonomous" agents. They care about: does it
**reliably** do the task every time, can I **trust** it with credentials and
production systems, and is it **transparent** about what it did.

**One-line positioning:**
> *Reliable, trustworthy agents that do real work — and keep getting better
> without breaking themselves.*

**The closing belief (use verbatim somewhere prominent):**
> *There are no limits to what Luna can be — we just built it with trust and
> reliability in mind.*

**Tone:** confident, concrete, engineer-credible. Show the architecture that
earns the trust (plugins, vault, rollback, deterministic workflows) — not vague
"AI magic." No hype words ("revolutionary"); let reliability/trust do the work.

## Goals

1. A multi-page marketing site at `luna.com.ai` that **explains all of Luna** and
   converts to signup.
2. A top-bar **Products ▾** menu with three explained destinations: **Luna Open
   Source**, **Luna Hosting Service**, **Luna Marketplaces**.
3. Three deep sections/pages: OSS (what it is + why open), Marketplaces (what they
   mean), Hosting Service (the benefits — the money page).
4. The **primary CTA everywhere = "Start free — sign up with Google"** (try Luna).
5. Informative, architecture-backed content drawn from the deck + vision, aimed at
   the reliability/trust-seeking audience.
6. Fast, mobile-first, SEO-crawlable, on-brand (dark, Luna moon identity).

## Non-Goals

- No new auth, billing, or signup *backend* — CTAs route into the **existing**
  Google OAuth flow (`/auth/...`) and dashboard. Stripe/checkout stays out (the
  vision still has billing as post-MVP).
- No blog/CMS engine in v1 (content lives in the repo as components/MDX; a blog
  can come later).
- No live marketplace browse experience here (we **describe** marketplaces and
  link out / "coming soon"; the actual marketplace UI is Luna-side, 008.5).
- No pricing *enforcement* — the Pricing page is informational (tiers from the
  vision), CTAs go to signup.
- No rebrand — reuse the existing Luna identity + design tokens.

## Decisions

- **D1 — Build it inside the existing `cloud/ui` React+Vite SPA, not a new
  stack.** Everything already ships as one SPA served by FastAPI from
  `cloud/ui/dist` (`cloud/main.py` `SPAStaticMiddleware`). Adding marketing as
  public routes reuses the build, deploy (one Render service), design tokens, and
  — crucially — makes "Start free" a same-app click into the existing OAuth. A
  separate Astro site (better raw SEO) is the documented fallback (D6) if SEO
  demand outgrows prerendering; not worth the second toolchain now.
- **D2 — Route precedence + slug safety.** New static marketing routes
  (`/products/*`, `/pricing`, `/oss`, …) are declared in `App.tsx` **above** the
  `/:slug` catch-all. React Router ranks static > dynamic, so `/pricing` never
  resolves to `UserLuna`. Add the reverse guard: a **reserved-word list** so an
  account slug can never be created as `products`, `pricing`, `oss`, `hosting`,
  `marketplace`, `login`, `signup`, `docs`, `about`, `security`, `blog`, etc.
  (enforced at agent/account slug creation in the control plane).
- **D3 — Logged-in vs logged-out at `/`.** Logged-out → marketing home.
  Logged-in → marketing home still renders, but the nav's primary button flips to
  **"Go to your Luna →"** (dashboard). No forced redirect (people re-read
  marketing/pricing while logged in).
- **D4 — Content is component-driven and editable.** Page copy lives in typed
  content modules (`cloud/ui/src/marketing/content/*`) so non-devs can tweak
  headlines/sections without touching layout. Source of truth = this plan's
  content map (deck + vision).
- **D5 — Conversion-first.** Every page ends with the same signup CTA band. The
  header CTA is persistent. Hosting Service is the default funnel; OSS and
  Marketplaces both include a "skip the setup — try hosted" cross-sell to signup.
- **D6 — SEO via prerender, not CSR-only.** Add static prerendering of the public
  marketing routes (e.g. `vite-react-ssg` or a `react-snap` post-build) so each
  page ships real HTML + meta/OG/sitemap for crawlers and link unfurls, while the
  app routes stay a normal SPA. (Fallback if this proves fiddly: standalone Astro
  site at root, app moves under the same domain — documented, not chosen.)

## Information architecture (site map)

```
Top bar:  🌙 Luna   [Products ▾]  Pricing   Docs↗   Open Source↗        [Sign in]  [Start free]
            Products ▾ = Luna Open Source · Luna Hosting Service · Luna Marketplaces

/                         Home (the full story, condensed, → deep pages)
/products/hosting         Luna Hosting Service   (PRIMARY money page)
/products/open-source     Luna Open Source
/products/marketplace     Luna Marketplaces
/pricing                  Pricing (Free / Pro / Power / Enterprise)
/security                 Trust & security deep-dive
/about                    Mission / the SR-SI story (from the deck)
(/docs, /open-source nav items link out to docs site + GitHub)
Footer: product links · OSS/GitHub · docs · security · pricing · legal stubs
```

## Page-by-page content (mapped to deck + vision)

### `/` Home
1. **Hero** — H1: *"Agents you can actually rely on."* Sub: second-gen
   self-improving agents built for **reliability and trust**, fit to own
   business-critical work. Buttons: **Start free** (primary) · *Explore the open
   source*. Eyebrow line naming the audience ("For the people who need agents that
   do real work — FDEs, ops, builders.").
2. **The problem** (deck p.10–12) — first-gen "Claw-style" agents: keep breaking,
   inconsistent execution, insecure → unreliable. Two root flaws: (1) unbounded
   self-coding can touch any key / override any constraint / wreck itself; (2)
   everything rides on raw LLM reasoning with no framework — chaos.
3. **The Luna difference — two pillars** (deck p.4–5):
   - **Reliability:** repeats tasks without failing; keeps self-improving
     *without breaking itself*; solid execution, no LLM volatility.
   - **Trust:** secure (no keys to the LLM, proper vault, safe on any
     environment); truthful (limits hallucination); operationally transparent (no
     black box on what it did).
   *…while staying fully self-reflective and self-improving.*
4. **How it works — the plugin scaffold** (deck p.14–16): everything is a plugin →
   Luna extends to any task; plugins can do anything **but can't touch the
   machine, keys, or act without approval**; one-way **vault** (keys never reach
   the LLM); **rollback on every change** so Luna can always see and undo what it
   changed; **deterministic workflows/playbooks** the agent *builds and improves*
   but does **not** run by raw reasoning; runs on the **cloud + a real DB**;
   adapts to any environment, even legacy systems — "exactly what you need and
   nothing more."
5. **Self-reflective / self-improving, made safe** (deck p.7–10) — the human-like
   loop (talk → it learns → it tries → you correct → it improves), but the
   improvement loop lives *inside the agent*, gated by the operator.
6. **What you can do** — concrete use cases for the audience: recurring ops
   reports, inbox/ticket triage, wiring legacy/internal systems via connectors,
   scheduled autonomous tasks (triggers), agent-built internal tooling.
7. **Trust & security strip** (vision §2/§7) — physical per-tenant isolation,
   per-tenant vault key we can't read, we never look at your data, transparent
   audit.
8. **Products triptych** — three cards → the three product pages.
9. **Pricing teaser** — "One bill. No API keys to manage. Use any model." → Pricing.
10. **Closing CTA band** — the "no limits … built with trust and reliability"
    line + **Start free**.

### `/products/hosting` — Luna Hosting Service  *(primary)*
- Promise (vision §TL;DR): sign up with Google → ~60s → your own private,
  isolated, persistent Luna. No installing, no sysadmin.
- Benefit blocks (vision):
  - **One bill, no BYOK, pick any model** — never touch an Anthropic/OpenAI key;
    switch Opus/Sonnet/Haiku/GPT/Gemini freely; one usage meter.
  - **Physical isolation** — own microVM, DB schema, vault key, MCP subprocesses.
  - **We never see your data** — per-tenant keys, no conversation telemetry.
  - **Always-on & triggers** (paid) — "email me a summary at 9am"; autonomy.
  - **Fleet dashboard** — run many agents (one per project/client), costs visible.
  - **Polished UX** — as polished as ChatGPT, as private as self-hosting, that
    actually *does* things.
- "Hosted vs self-host" honest comparison table (convenience vs control).
- CTA: **Start free**.

### `/products/open-source` — Luna Open Source
- What it is: the agent itself, **MIT**, self-host on a $5 VPS; the whole platform
  that makes Luna work is open (`OPEN-PLATFORM.md`), revenue is verticals + hosting.
- Why open & why it's trustworthy *because* it's open (you can read the vault,
  rollback, approval-gate code).
- The architecture in brief (plugins, bonded security plugins, vault, rollback).
- The **open-platform promise** (never relicense backwards; if we break it, you
  have a fork).
- CTAs: **Star on GitHub↗ / Read the docs↗**, plus a soft *"want it without the
  setup? → Start free on hosting."*

### `/products/marketplace` — Luna Marketplaces
- **What a marketplace means for Luna:** Luna is "everything is a plugin," so a
  marketplace is how you **add capabilities** without forking — connectors, tools,
  channels, and **agent templates** ("Marketing Agent," "Ops Agent") plus
  **knowhow / vertical packs**.
- Two layers (from `OPEN-PLATFORM.md` + Luna 008.5 marketplace work): **OSS
  plugins** (free, community) and **commercial packs** (vertical, entitlement-checked).
- How it works: browse → one-click add → installed per-agent, isolated. Hosted
  users get curated install; OSS users get the SDK to build & publish.
- Honest status: framework shipping in Luna (008.5); on hosting it surfaces as
  one-click add. Mark genuinely-future items "coming soon" (no fake catalog).
- CTA: **Start free** (to get a Luna you can add to) + *Build a plugin↗* (SDK).

### `/pricing`
- Free / Pro / Power / Enterprise table (vision § Pricing). Reinforce **one bill,
  no BYOK, any model**; usage meter; graceful budget behavior. Per-tier CTA →
  signup (Enterprise → contact).

### `/security` and `/about`
- `/security`: the trust deep-dive (isolation, vault one-way, no-data-access,
  approval gates, rollback, transparency) — the page you send to a skeptical ops
  lead.
- `/about`: the mission + the SR-SI generational story from the deck.

## Architecture / where it lives

- New folder `cloud/ui/src/marketing/` — `layout/` (MarketingHeader with Products
  dropdown, Footer, CTA band), `pages/` (Home, Hosting, OpenSource, Marketplace,
  Pricing, Security, About), `content/` (typed copy modules), `assets/`.
- `App.tsx`: add the static marketing routes **before** `/:slug`; keep `/`
  pointing at the new marketing Home (replacing the thin `Landing`).
- `cloud/main.py`: `RESERVED_PREFIXES` already protects `/api /auth /a/ …`;
  marketing is just SPA routes (the existing 404→`index.html` fallback already
  serves them). Add the **slug reserved-word guard** where slugs are created
  (`cloud/db/tenant_provisioner.py` / agent-create path) so marketing words can't
  be claimed as accounts.
- Build: same `cloud/Dockerfile` (`npm run build`). Add the prerender step (D6) to
  the build script so `/`, `/products/*`, `/pricing`, `/security`, `/about` emit
  static HTML + per-page `<title>/<meta>/<og>`; generate `sitemap.xml` + `robots.txt`.
- Auth wiring: header "Sign in" / "Start free" → existing Google OAuth entry;
  logged-in detection flips the primary button to "Go to your Luna" (reuse the
  session check the dashboard already uses).

## Design system

> **Living styleguide:** [`styleguide.html`](./styleguide.html) — a self-contained
> visual reference (open in a browser) that defines the marketing-site language:
> deep-space canvas, liquid-glass surfaces, the synthetic violet→cyan→pink
> spectrum, Space Grotesk / Instrument Serif / Inter type, the signature **moon
> eclipse reveal** motif, plus the header, buttons, cards, diagrams, hero,
> pricing and CTA patterns. Iterate on the look there before porting tokens into
> `cloud/ui`. Note: this is a *new* marketing language, intentionally richer than
> the current admin theme below.

- Reuse the existing dark theme + CSS custom properties (`var(--text)`,
  `var(--text-dim)`, etc. already used across admin pages) and the 🌙 brand.
- Mobile-first (vision: mobile is first-class); the Products menu collapses to an
  accordion in a mobile drawer.
- Visual motifs that *say* reliability/trust without stock-art: a "scaffold/plugin"
  diagram, a vault/one-way-key diagram, a rollback timeline, a deterministic
  workflow lane vs an "LLM chaos" lane (straight from the deck's contrast).
  Generate these as lightweight inline SVG/components, not heavy images.
- **Narrative imagery** lives in [`assets/`](./assets) — cohesive **photorealistic
  editorial photography** of real people in real workplaces (hero + open-source /
  hosting-service / marketplaces / reliability / trust-vault / self-improving),
  one cool-graded library, generated with Gemini Nano Banana Pro. Each shot
  conveys one idea so it explains the narrative at a glance; the moon stays as
  the brand mark, the content imagery is human (no stock-space art). Regenerate
  or extend with the `gemini-image` skill (`~/.cursor/skills/gemini-image/`).
  See them wired up in `styleguide.html` (Imagery section + product cards).
- Accessibility: semantic headings, keyboard-navigable dropdown, contrast AA.

## SEO & sharing

- Per-page title/description/canonical; OG + Twitter cards with a branded image.
- `sitemap.xml`, `robots.txt`; JSON-LD `Organization`/`SoftwareApplication` on Home.
- Prerendered HTML (D6) so crawlers and unfurlers see real content.

## Risks

- **Slug ↔ marketing path collision** → reserved-word guard (D2) + static-route
  precedence; test both directions.
- **SPA SEO weakness** → prerender public routes (D6); fallback to Astro only if
  needed.
- **Marketing bundle bloat in the app** → route-based code-splitting; marketing
  chunks load only on public routes.
- **Overclaiming** (marketplace/always-on not fully shipped) → label future items
  "coming soon"; keep copy truthful (the whole pitch is *trust*).
- **Copy drift from product reality** → content modules cite this plan; review
  against vision before publishing.

## Acceptance criteria

- [ ] `luna.com.ai/` shows the new marketing Home; `Products ▾` lists and links
      Luna Open Source, Luna Hosting Service, Luna Marketplaces.
- [ ] All pages exist and render: `/`, `/products/hosting`,
      `/products/open-source`, `/products/marketplace`, `/pricing`, `/security`,
      `/about`.
- [ ] Primary CTA ("Start free") appears on every page and lands in the existing
      Google OAuth signup; logged-in users see "Go to your Luna" instead.
- [ ] Content reflects the deck's Reliability+Trust pillars, the plugin/vault/
      rollback/workflow story, and the vision's one-bill/no-BYOK/isolation points.
- [ ] `/pricing` shows Free/Pro/Power/Enterprise with correct CTAs.
- [ ] No route collision: visiting `/pricing` etc. never renders `UserLuna`; an
      account slug cannot be created as a reserved marketing word.
- [ ] Mobile: nav drawer + Products accordion work; pages are legible and fast on
      a phone viewport.
- [ ] Each public page ships real prerendered HTML with unique title/meta/OG;
      `sitemap.xml` + `robots.txt` exist.
- [ ] The "no limits … built with trust and reliability" statement appears
      prominently.

## Verification (devprocess + dojo)

```bash
cd cloud/ui && npm run build && npm run preview   # build + prerender OK
cd cloud && .venv/bin/pytest tests/ -k "slug or reserved" -q   # slug guard
# dojo browser walkthrough (tests/021-marketing-website/):
#  - load luna.com.ai/ → hero + all home sections present (screenshot)
#  - open Products ▾ → click each of the 3 product pages → content correct
#  - click "Start free" from home, hosting, oss, marketplace, pricing → each
#    lands in Google OAuth signup
#  - visit /pricing, /security, /about directly (deep link) → correct page, not
#    UserLuna; view-source shows prerendered HTML + <title>/<meta og:>
#  - mobile viewport: drawer + Products accordion + CTAs work
#  - logged-in: primary button reads "Go to your Luna" → dashboard
# Screenshots → tests/021-marketing-website/screenshots/.
```

## Tests — tests/021-marketing-website/ (dojo scenarios, this repo)

- `01-home-and-nav.md` — home renders all sections; Products menu → 3 pages.
- `02-cta-to-signup.md` — every page's primary CTA reaches Google OAuth.
- `03-product-pages-content.md` — hosting/oss/marketplace key claims present &
  truthful (no fake catalog; "coming soon" where applicable).
- `04-routing-and-slug-guard.md` — deep-link marketing paths don't hit `UserLuna`;
  reserved slug words rejected at account creation.
- `05-seo-prerender.md` — view-source of each public page has unique
  title/meta/OG; sitemap.xml + robots.txt served.
- `06-mobile-and-logged-in.md` — mobile drawer/accordion; logged-in CTA flip.
