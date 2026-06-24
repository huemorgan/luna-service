# 022 — Marketplaces product page + Open Source ASCII redesign

> Two of the three product pages get their own visual identity and a sharper job.
> **Luna Marketplaces** becomes a *separate product* page — warm/yellow scheme,
> its own signup CTA (sign up → create your own marketplace), and a **downloadable
> Cursor environment** for building plugins (hosted on `marketplaces.com.ai`, so
> updating the zip there updates the download on our site). **Luna Open Source**
> gets an **ASCII / terminal** design language that signals "this is the real,
> hackable, MIT thing." Shared chrome (header/footer/brand) stays; only the page
> bodies and their CTAs change.

## Context

The 021 marketing site (`cloud/ui/src/marketing/`) ships seven pages in one React
+ Vite SPA, all scoped under a single `.mkt` CSS namespace, wrapped by
`MarketingLayout` (Header → `<Outlet/>` → shared `CtaBand` → Footer). Every page
currently shares one design language (deep-space violet→cyan→pink) and one CTA:
`StartFree` → `/auth/login` (Google → hosted Luna).

Two pages should now diverge:

- **Marketplaces is its own product.** The plugin/marketplace machinery lives in
  the Luna submodule — the **Plugin SDK** (`luna/luna_sdk/`, `luna-plugin-sdk` on
  PyPI, `luna plugin init` scaffolding, `luna.testing` harness; see
  `luna/plans/008.5-pluginsdk/` and `luna/plans/OPEN-PLATFORM.md`) and the
  two-layer model (OSS plugins + commercial vertical packs). The product story:
  **anyone can sign up to Marketplaces and create their own marketplace** (an org
  directory for employees; a vendor storefront for customers — see the existing
  "Open marketplaces" section already on the page). That deserves its own page
  identity and its own CTA, distinct from "Start free on hosting."

- **Open Source should *look* open.** The OSS audience is engineers who trust what
  they can read and run. An ASCII/terminal aesthetic (monospace, box-drawing
  diagrams, a real terminal-window hero, `$ luna plugin init`) says "MIT, hackable,
  yours" far better than the same glossy gradient every other page uses.

Voice for all copy follows `plans/website/copy-guidelines.md` (speak to the
reader's wish; cut adjectives; "you/your"; ≤6-word hero titles; honest "coming
soon" labels). The `OPEN-PLATFORM.md` promise and SDK facts are the source of
truth — no overclaiming.

## Goals

1. **Marketplaces page** (`/products/marketplace`) relaunched as a *separate
   product*: distinct **warm/amber ("yellow")** scheme, full "what it is / what
   you do here / why" narrative, and a **marketplace-specific CTA** (sign up →
   create your marketplace) pointing at `marketplaces.com.ai`.
2. A **downloadable Cursor plugin-dev environment** ("Luna Plugin Studio for
   Cursor") promoted on the Marketplaces page, hosted on `marketplaces.com.ai`,
   linked so **updating the zip there updates our download with no site rebuild**.
3. **Open Source page** (`/products/open-source`) restyled in an **ASCII/terminal**
   design language (monospace, ASCII box diagrams, terminal hero), keeping all the
   021 content (trust-because-open, lean core, expand anywhere, open-platform
   promise).
4. Per-page theming that **reskins only the page body + its CTA**, leaving the
   shared Luna header/footer/brand intact (cohesion across the site).
5. No regressions: routing, slug guard, SEO, mobile, and the hosted "Start free"
   funnel on the *other* pages all keep working.

## Non-Goals

- **Not building the `marketplaces.com.ai` site/app itself.** That's a separate
  product/build. Here we only (a) design the marketing page on `luna.com.ai`, (b)
  link its CTA out to `marketplaces.com.ai`, and (c) link the plugin-dev zip hosted
  there. If `marketplaces.com.ai` isn't live yet, the CTA/download degrade to a
  clear "coming soon" (D5).
- No new auth/billing in `luna-service`. The hosted funnel is unchanged; the
  *marketplace* signup is handled by the marketplace product, not here.
- No change to the Luna submodule. We *reference* the SDK; we don't edit it. (The
  actual zip contents are produced/owned on the marketplaces side — see D4.)
- No rebrand of the shared site chrome or the other five pages.
- No real plugin storefront/browse UI on `luna.com.ai` (still "describe + link").

## Decisions

- **D1 — Per-page sub-themes layered on `.mkt`.** Add two theme modifier classes,
  applied to each page's outer wrapper (inside the `Outlet`), that override design
  tokens locally:
  - `.t-ascii` (Open Source): monospace type stack (`'JetBrains Mono','IBM Plex
    Mono',ui-monospace,monospace`), near-black canvas, phosphor-green accent
    (`--accent:#7CFFB2`), box-drawing dividers, subtle scanline/grain, no rounded
    "glass" cards (square, hairline, terminal panels).
  - `.t-market` (Marketplaces): warm amber/gold accent (`--accent:#F5C518`,
    gradient amber→orange `--grad-market:linear-gradient(120deg,#F7B733,#FC4A1A)`),
    warmer surfaces, a "storefront" feel — clearly *not* the violet/cyan spectrum.

  Tokens are overridden as `.mkt .t-ascii { … }` / `.mkt .t-market { … }` so the
  base system still supplies layout/spacing; only color/type/shape change. Shared
  Header/Footer (outside the page wrapper) keep the base theme.

- **D2 — Page-owned CTA bands; make the shared band suppressible.** Today
  `MarketingLayout` always renders one `CtaBand` (hosted "Start free"). Change it
  so a page can opt out and render its own closing CTA. Mechanism: a tiny route →
  config map (or a React context flag set per page) — e.g. `marketplace` and
  `open-source` set `customCta`, so `MarketingLayout` skips the default band and
  the page renders a themed one (`MarketplaceCtaBand` / an ASCII CTA). Other pages
  are untouched.

- **D3 — New CTA component for Marketplaces.** Add `MarketplaceCta` (sibling to
  `StartFree`) → `MARKETPLACE_SIGNUP_URL` (`https://marketplaces.com.ai/` or
  `/signup` there). Label: **"Create your marketplace"** (primary) with a softer
  **"Browse Marketplaces ↗"** secondary. It is *not* the Google hosted-signup CTA
  — different product, different destination. (Open Source keeps GitHub/docs CTAs
  plus the existing soft "want it hosted? → Start free" cross-sell.)

- **D4 — Zip lives on `marketplaces.com.ai`; our link is indirection, not a
  bundled asset.** We do **not** commit the zip to `luna-service` (it would go
  stale and bloat the repo). Two layers:
  - Canonical artifact: `https://marketplaces.com.ai/downloads/luna-plugin-cursor.zip`
    (owned/updated on the marketplaces side; updating it is the single source of
    truth).
  - Our site exposes a **stable branded redirect**: `GET
    /downloads/luna-plugin-cursor.zip` on the FastAPI app → `302` to the canonical
    URL (target read from env `MARKETPLACE_PLUGIN_ZIP_URL`). The Marketplaces page
    button points at our redirect. Result: updating the zip on `marketplaces.com.ai`
    instantly changes what users get; the path on our side never changes; and we
    keep a branded, analytics-friendly URL. (Simpler fallback: link the canonical
    URL directly — chosen only if we don't want the redirect route.)

- **D5 — Graceful "coming soon" when `marketplaces.com.ai` isn't live.** A single
  flag (`MARKETPLACE_LIVE`, env-driven, surfaced to the SPA via the existing
  config/me endpoint or a build-time var). When false: the marketplace CTA renders
  as a non-routing "Marketplaces — coming soon" state and the download shows
  "coming soon," matching 021's honesty rule (no dead links, no fake catalog).

- **D6 — Styleguide-first, per theme.** Before porting either look into `cloud/ui`,
  build two self-contained references in this plan folder:
  `styleguide-ascii.html` and `styleguide-market.html` (same approach as 021's
  `styleguide.html`). Iterate on the visual language there, then port tokens +
  components into scoped CSS. Keeps design iteration out of the app build.

- **D7 — Imagery direction per theme.** ASCII page leans on *generated ASCII art /
  monospace diagrams* (inline, no photos) for the moon + the scaffold/vault/
  rollback diagrams — cheap, on-theme, crisp. Marketplaces keeps photoreal/editorial
  but **regraded warm** (amber, not cool-blue) for a storefront feel, generated
  with the `gemini-image` skill into `plans/022-.../assets/` then `cloud/ui/src/
  marketing/assets/`. Reuse 021's `marketplaces.png` only if a warm regrade reads
  consistently; otherwise regenerate.

## A) Open Source page — ASCII / terminal redesign

Keep **all** existing 021 content; restyle and re-sequence it in a terminal idiom.
Apply `.t-ascii` to the page wrapper.

**Design language (`.t-ascii`)**
- Type: monospace everywhere; headings in uppercase mono with tracked letters.
- Palette: `#05060A` canvas, `#0B0E13` panels, hairline `rgba(255,255,255,.10)`,
  phosphor accent `#7CFFB2`, dim text `#8a937f`-ish; one restrained green glow.
- Shape: square corners, 1px hairline panels styled as terminal windows (top bar
  with `● ● ●` dots + a title like `oss@luna:~$`). No glass blur, no pill buttons —
  buttons are `[ Star on GitHub ]` bracket-style.
- Motifs: ASCII box-drawing dividers (`╭─…─╮`), a blinking block caret, optional
  scanline overlay at low opacity; the **moon as ASCII art**.

**Section-by-section**
1. **Terminal hero** — a terminal window that "types": `$ luna plugin init` →
   `$ luna up` → `# your agent, your machine, MIT.` H1 (mono, ≤6 words): *"Open,
   all the way down."* Sub: one line. Buttons: `[ Star on GitHub ↗ ]`
   `[ Read the docs ↗ ]`.
2. **Why open** — "Trustworthy *because* it's open" as a commented code block /
   terminal output; the three points (vault, rollback, approval gates) as
   `# verifiable:` list items.
3. **Lean core, expand anywhere** — the six 021 cards rendered as ASCII panels;
   add an **ASCII architecture diagram**: a small `[ core ]` box with `[plugins]`
   hanging off it via box-drawing lines (lean center, capability at the edges).
4. **Open-platform promise** — rendered like a `LICENSE`/`PROMISE.txt` file in a
   terminal panel (mono, literal), quoting `OPEN-PLATFORM.md`.
5. **Cross-sell** — "want it without the setup?" as a dim shell comment →
   `[ Start free → hosted ]` (still the hosted CTA here; OSS funnels both ways).

Content sources: existing `OpenSource.tsx` copy + `OPEN-PLATFORM.md`. No claims
beyond MIT + the promise.

## B) Marketplaces page — separate product, warm scheme, new CTA

Apply `.t-market`. Reframe the page as **its own product** with a clear "what you
do here." Keep the strong 021 substance (trust/provenance model; open-marketplaces
for orgs & vendors; monetization note) and add the product framing + plugin-dev
download.

**Design language (`.t-market`)**
- Accent amber/gold `#F5C518`; primary gradient amber→orange; warm surfaces; the
  spectrum/glow swapped for golden glow. Storefront warmth, still dark-mode base.
- Moon motif tinted warm (eclipse in gold) to tie back to the brand without the
  cool palette.

**Section-by-section**
1. **Hero (product)** — H1 (≤6 words): *"Your own plugin marketplace."* Sub: one
   line — open a marketplace, fill it with trusted plugins, point your Lunas at it.
   **CTA: `MarketplaceCta` → "Create your marketplace"** (primary, amber) +
   "Browse Marketplaces ↗" (secondary). This replaces the hosted "Start free" as
   the page's primary action.
2. **What it is** — a marketplace = a plugin directory you trust, wired into your
   Lunas. (Carry over the "everything is a plugin" framing.)
3. **What you do here** (the new "separate product" core) — 3 steps:
   *Sign up → Create a marketplace → Add plugins & connect your Lunas.* Make the
   action concrete (this is the page's job).
4. **Who it's for** — keep the existing org + vendor cards ("roll your own internal
   directory; instant employee access" / "vendor storefront, unified access"),
   restyled warm.
5. **Trust model** — keep the provenance section (powerful plugins → trusted
   sources only; community at-your-own-risk), restyled warm.
6. **Build plugins → Cursor environment** *(new)* — promote **"Luna Plugin Studio
   for Cursor"**: a ready-to-open Cursor workspace for authoring Luna plugins.
   - What's inside (from the SDK reality): the `luna-plugin-sdk`, a scaffolded
     example plugin (`luna plugin init` output), `manifest.yaml` template with the
     `license:`/`requires_entitlement` fields, the `luna.testing` harness + mock
     servers, and **Cursor config** (`.cursor/rules/` for plugin-authoring guidance,
     optional `.cursor/mcp.json`), plus a README quickstart. (Exact manifest owned
     on the marketplaces side — D4.)
   - **Download button → `/downloads/luna-plugin-cursor.zip`** (our redirect →
     `marketplaces.com.ai`). Copy: "Download the Cursor plugin kit" + "Updated on
     `marketplaces.com.ai`."
7. **Monetization note** — keep: vendors own monetization today; a first-party
   paid-plugin wrapper may come later.
8. **Closing CTA band (themed)** — `MarketplaceCtaBand`: "Create your marketplace"
   (amber) — *not* the hosted band.

## Downloadable Cursor plugin-dev environment

- **Name:** "Luna Plugin Studio for Cursor" (working title).
- **Purpose:** open in Cursor → build/test a Luna plugin in minutes using the SDK.
- **Hosting & freshness:** canonical zip on `marketplaces.com.ai/downloads/…`;
  our site links via the `/downloads/luna-plugin-cursor.zip` redirect (D4) so the
  marketplaces team updates the kit without a `luna-service` deploy.
- **Out of scope here:** authoring the kit's contents (that's a marketplaces/SDK
  deliverable). This plan wires the link + download UX + redirect.

## Architecture / where it lives

- **Theming:** add `.t-ascii` / `.t-market` token overrides to a new
  `cloud/ui/src/marketing/themes.css` (imported by `marketing.css`). Wrap each
  page's content in `<div className="t-ascii">` / `<div className="t-market">`.
- **Layout/CTA:** update `MarketingLayout.tsx` to skip the default `CtaBand` for
  routes that own their CTA (config map or context). Add
  `components/MarketplaceCta.tsx` + `components/MarketplaceCtaBand.tsx`; add an
  ASCII CTA variant for OSS (or reuse `StartFree` styled by `.t-ascii`).
- **Constants:** extend `lib/constants.ts` —
  `MARKETPLACE_BASE_URL='https://marketplaces.com.ai'`,
  `MARKETPLACE_SIGNUP_URL`, `PLUGIN_CURSOR_ZIP_URL='/downloads/luna-plugin-cursor.zip'`,
  `MARKETPLACE_LIVE` (from config).
- **Backend (optional, D4):** add `GET /downloads/luna-plugin-cursor.zip` to
  `cloud/main.py` → `RedirectResponse(settings.marketplace_plugin_zip_url, 302)`;
  add `marketplace_plugin_zip_url` + `marketplace_live` to settings/env. Add both
  to `.env.example`. Keep robots: the redirect path is fine to leave crawlable.
- **Pages:** rewrite `pages/Marketplace.tsx` and `pages/OpenSource.tsx` only.
  `useSeo` titles/descriptions refreshed (OSS: "the MIT agent you can read and
  run"; Marketplace: "open your own plugin marketplace").
- **Build/deploy:** unchanged — `cloud/Dockerfile` `npm run build`; deploy via push
  to `main` (Render auto-deploy), per the 021 flow.

## Design system additions

- Two styleguides (D6): `plans/022-marketplace-oss-redesign/styleguide-ascii.html`,
  `…/styleguide-market.html`. Build/iterate first; then port tokens.
- New fonts: a monospace family (JetBrains/IBM Plex Mono) added to `index.html`
  Google Fonts for `.t-ascii`. Amber palette needs no new font.
- Keep AA contrast (phosphor-green on near-black; amber on dark both pass at the
  weights used).

## SEO & sharing

- Per-page `<title>/<meta>/<canonical>/og` via `useSeo` (already in place).
- Marketplaces OG image regraded warm; OSS OG can be an ASCII-art card.
- `sitemap.xml` unchanged (paths are the same).

## Risks

- **`marketplaces.com.ai` not live / not owned yet** → D5 "coming soon" fallback;
  redirect target env-gated. *Confirm domain ownership/plan (open question Q1).*
- **Theme bleed** — `.t-ascii`/`.t-market` overrides must stay scoped; verify the
  shared Header/Footer and the *other* five pages are visually unchanged.
- **Two more design languages = maintenance** → keep them token-only overrides on
  the shared layout, not parallel component trees.
- **Mono readability / mobile** — cap mono font sizes; ensure ASCII diagrams
  degrade to stacked panels on small screens (don't force wide `<pre>` to scroll).
- **Stale/oversized zip** if ever bundled → never bundle; redirect only (D4).
- **CTA confusion** (hosted "Start free" vs marketplace "Create your marketplace")
  → distinct labels, colors, and destinations; only one primary per page.

## Open questions (confirm before/with build)

- **Q1 — `marketplaces.com.ai`:** do you own it / will you register it, and should
  the marketplace **signup** land there (`/` or `/signup`)? Until it's live, ship
  D5 "coming soon"?
- **Q2 — Zip URL:** confirm the canonical path
  `marketplaces.com.ai/downloads/luna-plugin-cursor.zip` and that the redirect
  route (D4) is wanted (vs a direct link).
- **Q3 — Scope of "yellow":** reskin only the page body (recommended), or also
  flip the header CTA accent to amber while on the Marketplaces route?

## Acceptance criteria

- [ ] `/products/open-source` renders in the ASCII/terminal language (mono type,
      terminal hero, ASCII diagrams) with all 021 content intact; other pages
      unaffected.
- [ ] `/products/marketplace` renders in the warm/amber scheme, framed as a
      separate product, with a **"Create your marketplace"** primary CTA →
      `marketplaces.com.ai` (or "coming soon" per D5).
- [ ] The page includes the **Cursor plugin-dev environment** download → resolves
      to the `marketplaces.com.ai` zip via the `/downloads/luna-plugin-cursor.zip`
      redirect; updating the remote zip changes the download with no site rebuild.
- [ ] Shared header/footer/brand and the hosted "Start free" funnel on the other
      pages are unchanged.
- [ ] Mobile: both redesigns are legible; ASCII diagrams stack instead of
      overflowing.
- [ ] SEO: both pages keep unique title/meta/OG; sitemap/robots still valid.
- [ ] No route/slug regressions.

## Verification (devprocess + dojo)

```bash
cd cloud/ui && npm run build && npm run preview     # both themes compile/render
# (if redirect added) curl -sI http://localhost:8100/downloads/luna-plugin-cursor.zip
#   → 302 to the marketplaces.com.ai canonical URL
# dojo browser walkthrough (tests/022-marketplace-oss-redesign/):
#   - /products/open-source → ASCII look, terminal hero, content present (screenshot)
#   - /products/marketplace → amber look, "Create your marketplace" CTA → marketplaces.com.ai
#   - download button resolves/redirects to the marketplaces zip
#   - other pages unchanged; header/footer consistent
#   - mobile viewport: both pages legible, diagrams stack
# Screenshots → tests/022-marketplace-oss-redesign/screenshots/.
```

## Tests — tests/022-marketplace-oss-redesign/ (dojo scenarios)

- `01-oss-ascii.md` — OSS page is ASCII/terminal; all sections (why-open, lean
  core, promise) present; GitHub/docs + hosted cross-sell CTAs work.
- `02-marketplace-product.md` — warm scheme; "what you do here" steps; org/vendor +
  trust-model + monetization sections present.
- `03-marketplace-cta.md` — primary CTA is "Create your marketplace" → marketplaces.com.ai
  (or coming-soon); it is NOT the hosted Google signup.
- `04-plugin-cursor-download.md` — download button → redirect → marketplaces zip;
  copy states it updates on marketplaces.com.ai.
- `05-no-regression.md` — home/hosting/pricing/security/about + header/footer
  unchanged; hosted "Start free" still reaches Google OAuth.
- `06-mobile.md` — both redesigns legible on a phone; ASCII diagrams stack.
```
