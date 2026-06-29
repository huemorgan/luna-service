# 031 — Inline plugin images broken on hosted tenants (path-based fix)

Status: **suggestion / investigation** — not yet executed.
Author: diagnosis from a live debugging session against the tenant
`luna.com.ai/a/vaselin-test-0-13-016-8-5-pluginsdk-9849753-2`.

## TL;DR

Inline images from `plugin-image-gen` (and any plugin that serves a binary asset
the chat embed loads by URL) **fail to render on hosted tenants**, even though the
file exists and the URL is correct. The break is **at the Cloudflare edge in front
of `luna.com.ai`**, not in the plugin, not in luna-service app code, and not in
auth. We want to keep serving images **by path** (no base64 / data-URI embedding),
so the fix is to stop the edge from blocking the request that the chat's sandboxed
iframe makes.

## Symptom

In the chat, a generated image shows as a broken-image icon + alt text. The file
is reachable and is a valid JPEG. The plugin already emits the correct,
prefix-aware URL (`plugin-image-gen` 0.3.3 resolves the mount from
`document.baseURI` so the path is right at `/a/<slug>/chat/<id>` depth).

## Why this is an edge problem (evidence)

The chat renders each tool result's `embed_iframe` in an iframe with
`sandbox="allow-scripts"` — **no `allow-same-origin`**, so the iframe runs at an
**opaque / `null` origin**. Every test below was run live, inside that exact
sandbox context, on the tenant page:

| Test | Result |
|---|---|
| `fetch()` the image URL from the page (same-site) | **200 `image/jpeg`** |
| Same `fetch()` with `credentials: 'omit'` (no cookie) | **200 `image/jpeg`** — auth is **not** the gate |
| 0.3.3 mount script runs inside the `allow-scripts` srcdoc | **yes** — rewrites `src` to the correct absolute URL |
| `<img>` of an **external** image (picsum.photos) in that same null-origin sandbox | **LOADED** |
| `<img>` of a **`data:`** URI in that same null-origin sandbox | **LOADED** |
| `<img>` of the **luna.com.ai-hosted** image in that same null-origin sandbox | **ERROR** |
| Same luna image in a sandbox **with** `allow-same-origin` | **LOADED** |

Read that table carefully: in the **identical** sandbox, the browser happily loads
a cross-origin external image and a data-URI, but refuses the luna.com.ai-hosted
image. The only thing special about the failing request is that it targets
**our own zone** while carrying `Origin: null` / a non-same-site
`Sec-Fetch-Site` / empty referrer. That is an **edge rule on the `luna.com.ai`
zone**, not a browser behavior.

Response headers on the image confirm Cloudflare is the outermost layer:

```
server: cloudflare
cf-ray: a1332eed0f48d31d-TLV
cf-cache-status: BYPASS
via: 1.1 fly.io
x-render-origin-server: uvicorn
```

Chain: **Cloudflare → (fly / Render uvicorn = luna-service) → tenant Luna**.

## What it is NOT

- **Not the plugin.** `plugin-image-gen` 0.3.3 emits the right path; the file is a
  valid 200 JPEG. Bumping the plugin again will not fix it (we already proved
  0.3.0 → 0.3.3 never could — the URL was never the problem at this layer).
- **Not auth.** The asset returns 200 with `credentials: 'omit'`. `_resolve_agent`
  is not what's rejecting it for these GETs.
- **Not luna-service app code.** `cloud/api/proxy.py` forwards plugin asset bytes
  transparently and inspects **no** `Origin` / `Referer` / `Sec-Fetch-*` / CSRF
  header. `grep` across `cloud/` finds only `CORSMiddleware` (which does not gate
  `<img>` GETs) and the `SameSite=Lax` session cookie.
- **Not CORP/CORS headers on the response.** There is no
  `Cross-Origin-Resource-Policy` header at all; CORS is irrelevant to plain
  `<img>` display.

## Root cause

A Cloudflare feature on the `luna.com.ai` zone is rejecting image subresource
requests that originate from the chat's **null-origin sandboxed iframe** (foreign
`Origin`/`Sec-Fetch-Site`, empty referrer). The most likely candidates, in order:

1. **Scrape Shield → Hotlink Protection.** Purpose-built to block image requests
   (`.jpg/.png/.gif/...`) that don't come from the zone itself. A null-origin
   sandbox is exactly the "foreign request" it targets — and it only affects
   images, which matches the symptom precisely (text/HTML/JSON proxy fine, only
   images break).
2. **Bot Fight Mode / managed WAF.** A no-cors image request from a `null` origin
   can look "non-browser" and get challenged; the challenge HTML is not an image,
   so `<img>` errors.
3. **A custom WAF rule** keying on `Origin`/`Sec-Fetch-Site`.

We have not yet read the dashboard to confirm which one — see Verification.

## The fix (keep paths, no embedding)

Goal: the sandboxed chat iframe must be able to `GET` a tenant plugin asset by URL.

### Step 1 — Identify the exact Cloudflare rule (required first)

In the Cloudflare dashboard for the `luna.com.ai` zone:
- **Security → Events**: reproduce the broken image, then find the blocked
  request to `/a/<slug>/api/p/plugin-image-gen/file/<id>.jpg`. The event names the
  service/rule that blocked it (Hotlink Protection, Bot Fight, WAF rule id).

### Step 2 — Allow plugin asset GETs at the edge

Depending on Step 1, do the minimal thing:
- **Hotlink Protection:** turn it **off** for the zone (Scrape Shield →
  Hotlink Protection). It protects nothing we need and breaks our own embeds.
- **Bot Fight Mode / managed WAF:** add a **skip / allow** rule for the asset
  paths so legitimate same-domain embeds pass. Suggested matcher:

  ```
  (http.request.uri.path contains "/api/p/" and
   (http.request.uri.path contains "/file/" or
    http.request.uri.path contains "/read/" or
    http.request.uri.path contains "/ui/"))
  ```

  Action: **Skip** → Bot Fight Mode + relevant managed rulesets, for `GET`.

Scope it to the read-only asset prefixes (`file`, `read`, `ui`) — not the whole
tenant surface — so we don't loosen anything else.

### Step 3 — Defense-in-depth in luna-service (so it survives any future COEP)

In `cloud/api/proxy.py`, when proxying a tenant response whose path matches the
plugin asset prefixes above, set on the streamed response:

- `Cross-Origin-Resource-Policy: cross-origin`
- `Access-Control-Allow-Origin: *` (these are public, unguessable-id assets)

This guarantees the null-origin iframe can embed the bytes even if a future
`Cross-Origin-Embedder-Policy` is added to the app shell. It is a no-op for the
current breakage (the edge is the gate today) but makes the path-based contract
explicit and robust.

> Note: today these plugin asset routes return 200 to a no-cookie same-site
> fetch, i.e. they are effectively public (ids are random uuid4, traversal is
> rejected by the plugin). If we later decide they must be session-gated, prefer a
> **signed, time-limited query token** appended to the URL (works for tag-based
> `<img>`/`<iframe>`/`<a>` loads that cannot send headers) over a cookie — the
> same pattern `plugin-files` already uses with `?token=`. That keeps the
> path-based approach intact.

## Verification

1. Repro the edge block with the null-origin sandbox probe (load an external image
   + a data-URI + the luna image in `sandbox="allow-scripts"`; only the luna image
   should fail before the fix).
2. Apply Step 2.
3. Re-run the probe: the luna-hosted image must now **LOAD** in the null-origin
   sandbox.
4. In the live tenant chat, generate an image and confirm it renders inline at
   `/a/<slug>/chat/<id>` with no broken-image icon.
5. Confirm `plugin-files` image/PDF previews still work (same asset class).

## Explicitly rejected: embedding (data: URIs)

We are **not** inlining image bytes into the embed HTML. It bloats every stored
conversation, is awkward for large/multiple images, and hides the real defect (a
zone misconfiguration). Images stay **path-served**; the fix makes the path work.

## Out of scope

- Tenant plugin version delivery (baked image / managed install) — that is the
  separate question of getting 0.3.3 onto a tenant; this plan is purely about why
  a correctly-served image still won't render.
- Any change inside the `luna/` submodule.
