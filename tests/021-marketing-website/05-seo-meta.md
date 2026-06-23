# 05 — Per-page SEO meta + robots/sitemap

**Goal:** Each public page sets a unique title/description/OG; robots.txt + sitemap.xml are served.

## Pass criteria
- `document.title` is unique and descriptive on `/`, `/products/*`, `/pricing`, `/security`, `/about`.
- `<meta name="description">` and `og:title`/`og:description` update per page.
- `GET /robots.txt` → 200 text; `GET /sitemap.xml` → 200 xml listing the public routes.
- NOTE: full static prerender (D6) is deferred; meta is set client-side for now.
