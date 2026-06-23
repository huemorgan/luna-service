# 02 — Every primary CTA reaches Google OAuth

**Goal:** "Start free" on every page lands in the existing Google OAuth signup (`/auth/login`).

## Steps
For each of `/`, `/products/hosting`, `/products/open-source`, `/products/marketplace`, `/pricing`:
1. Find the primary **Start free** button (header + closing CTA band).
2. Confirm its `href` is `/auth/login` (or it navigates there on click).

## Pass criteria
- Header **Start free** href = `/auth/login` on every page.
- Closing CTA band **Start free** href = `/auth/login` on every page.
- Pricing: Free/Pro/Power CTAs → `/auth/login`; Enterprise → contact (mailto or /about).
