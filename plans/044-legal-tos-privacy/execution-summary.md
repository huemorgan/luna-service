# 044 — Public TOS + Privacy Policy: execution summary

## What shipped

**Legal documents** (canonical drafts in `plans/044-legal-tos-privacy/drafts/`, rendered at
https://luna.com.ai/terms and https://luna.com.ai/privacy):

- **Terms of Service** — Novalystrix named as operator; the hosted Service (luna.com.ai)
  explicitly differentiated from the Luna open-source project (OSS governed by its repo
  licenses, Service by these Terms); agents-act-on-your-behalf so consequences are the
  user's (CAPS disclaimer, Cursor-style); third-party credentials: Luna personnel do not
  log into user accounts; user IP stays the user's, with a license for us to learn from
  the Service — analyze Content, sessions, usage — to develop, train, and improve our
  software, systems, and AI models; Marketplace plugins AS-IS; credits non-refundable;
  AS-IS/AS-AVAILABLE warranty disclaimer; liability cap = greater of 6 months' fees or
  US $100 (Anthropic-style), agent/plugin actions excluded entirely; indemnification;
  Israel governing law; binding individual arbitration + class waiver with 30-day email
  opt-out (Cursor-style); contact legal@luna.com.ai.
- **Privacy Policy** — collects account, content + sessions, usage, billing data; states
  plainly that we use this data statistically to learn and to develop, train, and improve
  our software, systems, and AI models; what we do NOT do: no logging into accounts, no
  using stored agent credentials, no selling data, user IP remains theirs; sharing,
  retention, security, rights, children 16+, international transfers; privacy@luna.com.ai.

**Serving** — `/terms` and `/privacy` as marketing SPA routes ([App.tsx](../../cloud/ui/src/App.tsx)),
text in [legal.ts](../../cloud/ui/src/marketing/lib/legal.ts) rendered by a minimal
[Markdown.tsx](../../cloud/ui/src/marketing/components/Markdown.tsx); added to
`MARKETING_PATHS` in [main.py](../../cloud/main.py) (server-side route whitelist + sitemap).
Footer gains a Legal column; copyright line now names Novalystrix as operator.

**Signup consent (checked by default, per request)** — signup is Google-OAuth-only (no
form), so consent is a modal gate on every logged-out login entry point
([cta.tsx](../../cloud/ui/src/marketing/components/cta.tsx) `ConsentModal` + `LoginGate`,
wired into `StartFree` and both Header sign-in buttons): checkbox pre-checked, links to
/terms + /privacy, Continue-with-Google disabled while unchecked, plus a
"By continuing you agree…" sign-in-wrap line as the stronger backstop.

**Server-side consent recording** — `users.tos_version` + `users.tos_accepted_at`
(alembic 0009; `POST_BASELINE_COLUMNS` in migrate.py updated so pre-Alembic fingerprinting
still passes). `TOS_VERSION = "2026-07-16"` in auth_routes.py; stamped on user creation
and re-stamped whenever a login arrives with a different stored version — existing users
get consent recorded on their next login.

**Marketing copy aligned** — Home, Hosting, Security previously claimed "we never look at
your data / no conversation telemetry / no training on your work", which the new policy
contradicts. Rewritten to: your IP stays yours, credentials stay sealed, we learn from
sessions/usage statistically to improve Luna and our models — never to act in your
accounts. **Roy should review this deliberate positioning change.**

**Marketplace (separate repo, luna-marketplaces 55a9305)** — signup card gains a
checked-by-default consent checkbox linking to the canonical luna.com.ai/terms +
/privacy; `signup()` and `signupGoogle()` refuse if unchecked. Local checkout was ~30
commits behind origin; rebased cleanly, consent markup verified intact after rebase.

## Tests

- New [test_tos_consent.py](../../cloud/tests/test_tos_consent.py): new user stamped with
  current version; old-version user re-stamped on login; same-version login keeps the
  original stamp — 3 passed.
- Full cloud suite: **635 passed, 1 skipped** (after the migrate.py fingerprint fix — the
  two migration tests fail without it because legacy DBs lack the 0009 columns).
- UI build clean.

## E2E results (prod, HTTP-level — no browser tooling available)

- **S1 legal pages** — PASS. https://luna.com.ai/terms and /privacy return 200; sitemap.xml
  lists both; the served JS bundle (index-DkmPZlqS.js) contains the Terms/Privacy text,
  "operated by Novalystrix", and the training/improvement language.
- **S2 signup consent** — PASS at HTTP level. Bundle contains the consent modal markup
  (`consent-overlay`, `consent-card`, "By continuing you agree"); modal interaction itself
  not exercised (no browser). Server-side recording covered by the 3 unit tests.
- **S3 marketplace consent** — PASS. https://luna-marketplaces.onrender.com signup page
  contains the `signup-tos` checkbox and links to luna.com.ai/terms + /privacy.
- **Migration 0009** — applied in prod: deploy log shows the pre-start migrate run at
  revision 0008 upgrading to head, and the next restart reports
  "[migrate] database at revision 0009".

## Deploy

- luna-service: main c5dc3d0 (merge of 044-legal-tos-privacy, 548f631), Render deploy via
  API (autoDeploy off), migration 0009 runs pre-start.
- luna-marketplaces: 55a9305 pushed (via huemorgan2 token; repo lives under huemorgan2),
  Render srv-d8m7nct8nd3s73dofrm0 deployed via API (autoDeploy off there too).

## Considerations for Roy

1. **Not a lawyer.** These documents follow patterns from Anthropic, Cursor, and Supabase
   terms, but nobody licensed has reviewed them. Counsel review recommended before
   relying on them, especially arbitration and the liability cap.
2. **Pre-checked checkbox is weak consent evidence** in the EU (CJEU *Planet49*: a
   pre-ticked box is not valid consent). The "By continuing you agree…" line plus the
   server-side version/timestamp recording is the actual legal backstop; the checkbox is
   UX per your instruction.
3. **Training-by-default with no opt-out is aggressive under GDPR** for EU users. Most
   peers (Anthropic, OpenAI API) either don't train on customer content or offer opt-out.
   Fine while the allowlist keeps the user base internal; revisit before opening signup.
4. **Israel governing law is an assumption** based on Novalystrix — confirm the entity's
   jurisdiction; the arbitration seat follows it.
5. **Marketing claims changed** (see above) — the old "we never look at your data" pages
   directly contradicted the new policy and would have been the worse legal position.
6. **Luna OSS is still MIT in practice** (pyproject says MIT, no LICENSE file; the
   AGPL-3.0 switch from plan 040 exists only in vision.md), so the Terms reference the
   repo's licenses generically instead of naming one.
7. **legal@ / privacy@ luna.com.ai** are cited in the documents — make sure those
   addresses exist or alias somewhere.
