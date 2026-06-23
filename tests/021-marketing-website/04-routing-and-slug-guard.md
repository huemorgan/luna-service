# 04 — Routing precedence + reserved slug guard

**Goal:** Marketing paths never resolve to `UserLuna`; reserved words can't become account slugs.

## Steps
1. Deep-link directly to `/pricing`, `/security`, `/about`, `/products/hosting`.
2. Confirm each renders the marketing page, NOT the `UserLuna` iframe/loader.
3. Backend: a new account whose derived slug equals a reserved word (e.g. `pricing`) is suffixed instead.

## Pass criteria
- All marketing deep-links render marketing content (no `Setting up your Luna…`).
- `cloud/api/auth_routes.py` `_make_slug` path rejects/suffixes reserved words (`pricing`, `security`, `about`, `products`, `oss`, `hosting`, `marketplace`, `login`, `signup`, `docs`, `admin`, `dashboard`, `api`, `auth`, …).
