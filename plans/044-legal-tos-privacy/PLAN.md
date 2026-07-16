# 044 — Public Terms of Service + Privacy Policy, wired into signup

> Publish a TOS and Privacy Policy for the Luna Service (luna.com.ai +
> marketplaces.com.ai) that takes the industry's maximum-protection posture
> (AS-IS, liability cap, user indemnity, arbitration + class waiver, broad
> learn/train license) while keeping user IP with the user; identify
> Novalystrix as the operator and differentiate the hosted Service from the
> Luna open-source software (AGPL-3.0 core / Apache-2.0 SDK). Surface both in
> the signup flow with consent recorded server-side.

## Research basis

Patterns taken from Anthropic consumer terms (liability cap = greater of
6-months-fees or $100; Materials license to improve/train unless opt-out),
Cursor/Anysphere (auto-executed code: "YOU ARE SOLELY RESPONSIBLE FOR ANY
IMPACT"; arbitration + class waiver with 30-day opt-out), Supabase (hosted
service defined separately from OSS; AS-IS; consequential damages excluded),
and common agent-platform terms (AS IS / AS AVAILABLE / SOLELY AT YOUR OWN
RISK; $100-or-12-month-fees caps; AAA arbitration; class waivers). Roy's
posture: least accountability, maximum freedom to learn from all data and
usage (review sessions, statistical learning, train our AI models), user IP
stays the user's, we never log into user accounts or use their data for
anything but learning/improvement.

## Deliverables

1. **Documents** (canonical drafts in `drafts/`, rendered in the app):
   - Terms of Service — operator Novalystrix; Service vs Open Source split;
     agent-actions-are-yours; marketplace/plugins AS-IS; your-IP-is-yours +
     broad learn/train license; credits non-refundable; AS-IS warranty
     disclaimer; liability cap (greater of 6-month fees or $100), agent/plugin
     actions excluded; indemnity; arbitration + class waiver (30-day opt-out);
     Israel governing law.
   - Privacy Policy — what we collect (account, content+sessions, usage,
     billing); explicit "we review sessions and statistically learn, and use
     data to develop, train, and improve our AI models"; what we DON'T do (no
     logging into user accounts, no use of their credentials, no sale of
     data, user IP stays theirs); sharing, retention, rights, children,
     transfers.

2. **Pages** — `/terms` and `/privacy` under the marketing SPA:
   - `cloud/ui/src/marketing/pages/{Terms,Privacy}.tsx` rendering the docs.
   - Routes in `cloud/ui/src/App.tsx`; add paths to `MARKETING_PATHS` in
     `cloud/main.py` (+ sitemap).
   - Footer: Legal links (Terms, Privacy) in
     `cloud/ui/src/marketing/layout/Footer.tsx`; keep "© {year} Luna" but add
     "operated by Novalystrix" attribution.
   - Fix stale "The MIT agent" blurb in `marketing/lib/constants.ts` →
     AGPL-3.0 (differentiation goal).

3. **Signup consent** (auth is Google-OAuth-only, no form):
   - CTA "Start free" opens a consent step: checkbox **checked by default**
     "I agree to the Terms of Service and Privacy Policy" (links) + Continue
     with Google (`/auth/login?tos=1`). Button disabled if unchecked.
   - Header "Sign in" keeps direct link but gains microcopy "By signing in
     you agree to the Terms." (sign-in-wrap backstop).
   - Server-side recording: `User.tos_accepted_at` + `User.tos_version`
     (Alembic `0009_tos_consent`); set in `_upsert_user_and_account` on
     create and on login when version is missing/outdated. `TOS_VERSION`
     constant = effective date.

4. **Marketplace** — marketplaces.com.ai signup (separate repo
   `luna-marketplaces`, email/password): add the same checked-by-default
   consent line linking to luna.com.ai/terms + /privacy. (Its TOS coverage is
   in the main document's Marketplace section.)

## E2E scenarios (`tests/044-legal-tos-privacy/`)

- S1 — /terms and /privacy render publicly (no auth), correct content,
  linked from footer.
- S2 — signup consent: Start free shows pre-checked consent; unchecking
  disables continue; sign-in records tos_accepted_at/tos_version in DB.
- S3 — marketplace signup shows consent line linking to the policies.

## Risks / notes

- **Not legal advice — counsel review recommended** before relying on it:
  pre-checked boxes are weak consent evidence in the EU (Planet49); training-
  by-default without opt-out is aggressive under GDPR; total liability
  disclaimers can't waive non-waivable liability. The "By continuing you
  agree" sign-in-wrap + server-side recording is the enforceability backstop.
- Governing law set to Israel on the assumption Novalystrix is Israeli —
  confirm with Roy.
- Working tree has unrelated WIP (billing/043) — commit only 044 files.
- Never touch `luna/` submodule; `cloud/uv.lock` never committed.
