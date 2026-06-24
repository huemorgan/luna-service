# 05 — No regression on the rest of the site

**Goal:** only the OSS + Marketplaces page bodies changed; shared chrome and the
hosted funnel are intact.

## Steps
1. Load `/` (home), `/products/hosting`, `/pricing`, `/security`, `/about`.
2. Confirm each still renders in the original violet/glass scheme.
3. Confirm the shared header (Products / Pricing / Security) and footer look the
   same on every page, including the OSS and Marketplaces pages.
4. Click "Start free" on home/hosting/pricing → reaches Google OAuth (`/auth/login`).

## Pass
- The five non-redesigned pages are visually unchanged.
- Header/footer consistent across all pages.
- Hosted "Start free" still works.
