# 06 — Mobile drawer + logged-in CTA flip

**Goal:** Mobile nav works; logged-in users see "Go to your Luna".

## Steps
1. Set a phone viewport (e.g. 390×844). Open `/`.
2. Open the mobile menu (hamburger). Expand the Products accordion.
3. With a logged-in session (`/api/auth/me` → 200), reload `/`.

## Pass criteria
- Mobile: hamburger opens a drawer; Products expands to an accordion; CTAs are reachable; layout is legible (no overflow).
- Logged out: header shows **Sign in** + **Start free**.
- Logged in: primary header button reads **Go to your Luna →** (→ `/dashboard`); no "Sign in".
