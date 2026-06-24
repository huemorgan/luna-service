# 03 — Marketplace CTA is its own, not the hosted signup

**Goal:** the Marketplaces page's primary CTA is "Create your marketplace" →
`marketplaces.com.ai`, not the Google hosted signup.

## Steps
1. Load `/products/marketplace`.
2. Inspect the hero primary button and the closing CTA band button.
3. Confirm label is "Create your marketplace" (primary) with a "Browse
   Marketplaces ↗" secondary.
4. Confirm `href` points at `https://marketplaces.com.ai` (not `/auth/login`).
5. Confirm the bottom of the page does NOT show the generic hosted "Start free"
   band (this page owns its CTA).

## Pass
- Primary CTA → `marketplaces.com.ai`.
- No hosted "Start free" band at the foot of the marketplace page.
