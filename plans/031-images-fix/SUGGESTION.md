# 031 — Inline plugin images broken on hosted tenants

Status: **ROOT CAUSE FOUND (corrected)** — verified live on
`luna.com.ai/a/vaselin-test-0-13-016-8-5-pluginsdk-9849753-2` (DuckDuck, luna
v0.21.001), 2026-06-29.

## TL;DR (the answer)

The break is **`loading="lazy"` on the `<img>` inside the chat's sandboxed
embed**. It is **NOT** the Cloudflare edge, **NOT** auth, **NOT** the proxy,
**NOT** the URL. The chat renders each embed in a `sandbox="allow-scripts"`
iframe (opaque/`null` origin). In that context a `loading="lazy"` image never
fires its load, so it sits forever unloaded → broken-image icon. The same URL,
loaded eagerly in the *identical* sandbox, renders fine.

**Fix (plugin side, one line):** in `plugin-image-gen`'s embed HTML, drop
`loading="lazy"` from the `<img>` (use eager loading). Done.

> This corrects the earlier version of this doc, which blamed a Cloudflare rule
> (Hotlink Protection / Bot Fight). That was wrong — see the live evidence below.
> The original comparison tested *lazy* luna images against *non-lazy*
> external/data-URI images, so it mis-attributed the difference to origin/edge
> instead of the `loading` attribute.

## Live evidence (all run inside the real chat page)

The actual broken embed's srcdoc (from the live DOM) contains:

```html
<img id="img" src="api/p/plugin-image-gen/file/<id>.jpg"
     alt="..." loading="lazy">
<script>/* rewrites img.src to the absolute /a/<slug>/api/p/... URL */</script>
```

1. **Asset is reachable.** From the page, `fetch(absUrl)` →
   `200 image/jpeg`; with `credentials:'omit'` → **also `200 image/jpeg`**. So
   it is not auth- or edge-gated for the GET.
2. **Edge does NOT block null-origin image loads.** In a freshly created
   `sandbox="allow-scripts"` iframe (same opaque origin as the chat embed),
   three `<img>`s were loaded: an external `picsum.photos` image, a `data:` URI,
   **and the luna.com.ai-hosted image — all LOADED** (luna image = 1024×1024).
3. **The plugin's URL rewrite is correct.** Inside the opaque srcdoc iframe
   `document.baseURI` resolves to the parent
   (`…/a/<slug>/chat/<conv-id>`); the mount script strips `/chat/<id>` and
   produces `…/a/<slug>/api/p/plugin-image-gen/file/<id>.jpg` — the right URL.
4. **Isolation test — the only variable that matters is `loading`:**

   | embed `<img>` (everything else identical) | result |
   |---|---|
   | `loading="lazy"` src=absolute | **broken (0×0)** |
   | eager src=absolute | loads (1024) |
   | eager, src=relative then JS-rewrite to absolute | loads (1024) |
   | `loading="lazy"`, src=relative then rewrite (the **exact** real embed) | **broken (0×0)** |

   `loading="lazy"` alone breaks it; removing it fixes it.

## Why lazy fails here

`loading="lazy"` defers the fetch until the browser thinks the image is near the
viewport. Inside the chat's `sandbox="allow-scripts"` (no `allow-same-origin`)
iframe, that visibility/intersection signal doesn't resolve, so the deferred
load is never triggered — the image stays unloaded regardless of whether the
embed is actually on screen. Eager images bypass the deferral and load normally.

## The fix

### Plugin (`plugin-image-gen`) — the real fix
Remove `loading="lazy"` from the embed `<img>` (plain eager `<img src=…>`). These
embeds are single, immediately-visible chat images — lazy buys nothing and breaks
them in the sandbox. Optionally also set it on the `plugin-files` previews if they
embed images the same way.

### luna-service — nothing required
No Cloudflare change. No `cloud/api/proxy.py` change. The asset already serves
`200 image/jpeg` to the sandboxed, no-cookie request. (The previously suggested
CORP/`Access-Control-Allow-Origin` headers are unnecessary for this bug — they
were defending against a non-issue.)

## Verification after the plugin fix
1. Generate an image in chat → it renders inline (no broken icon).
2. Re-run the sandbox isolation probe: the `loading="lazy"` row should be the
   only thing that ever failed, and the shipped embed no longer uses it.
3. Confirm `plugin-files` image/PDF previews still render.
