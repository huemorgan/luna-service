# Proposal for luna-plugins — fix browser screenshots silently dropping to inline

> PROPOSAL written in the luna-service repo. Nothing in `luna-plugins/` is
> touched from here. If accepted, the luna-plugins team applies it in their repo
> and republishes the affected plugins to the marketplace.
>
> Companion: `luna-suggestion-capability-load-order.md` (the core-side fix that
> makes this class of bug impossible). Either fix alone resolves the symptom;
> we recommend shipping both.

## Symptom

On a fully up-to-date agent (luna core ≥ 0.19, `plugin-files` 0.4.0+,
`plugin-browser` 0.3.1), `browser_screenshot` never saves to the Files area. The
agent reports the screenshot inline with the note:

> "No storage provider enabled; screenshot returned inline only."

…even though `plugin-files` is loaded and `file_write` works fine. It is **not**
a version problem and **not** a per-agent config problem — it reproduces
deterministically.

## Root cause — load order + load-time capture

Two independent facts combine into the bug:

1. **`plugin-browser` captures the storage provider once, at `on_load`** — and
   closes over that value for the lifetime of the plugin:

   ```python
   async def on_load(self, ctx: PluginContext) -> None:
       ...
       storage = getattr(ctx, "storage", None)   # bound ONCE, here
       async def _screenshot(...):
           ...
           out = await _save_screenshot(storage, b64)   # uses the closed-over value
   ```

2. **Core orders plugin loading by `(tier, name)` and only `depends_on` creates
   ordering edges — `capabilities` do not.** Tier comes from `type` /
   `system_app`, **not** `category`.
   - `plugin-files`: `category="system"` but no `type=SYSTEM` / `system_app=True`
     → tier 2 (USER).
   - `plugin-browser`: no type/system_app, no `depends_on` → tier 2 (USER).

   Same tier, no edge → tie-break by name. `"plugin-browser"` < `"plugin-files"`
   alphabetically, so **browser loads first**. At that moment `plugin-files` has
   not yet registered the `"storage"` provider, so `ctx.storage` is `None`.
   Browser captures `None` permanently → every screenshot takes the inline
   fallback.

`file_write` is unaffected because it's a plain tool on `plugin-files`, not the
`StorageProvider` capability — which is why "files work" but screenshots don't.

## Fix (recommended): resolve `ctx.storage` at call time

Move the lookup out of `on_load` and into the tool body so it sees whatever is
registered at call time (and survives a later `register`/`replace`).

```python
async def on_load(self, ctx: PluginContext) -> None:
    vault = getattr(ctx, "vault", None)
    events = getattr(ctx, "events", None)
    # do NOT bind storage here

    async def _screenshot(...):
        ...
        storage = getattr(ctx, "storage", None)   # resolve per call
        out = await _save_screenshot(storage, b64)
```

This is a one-symbol move, has no API impact, and makes the plugin robust to any
load order. Apply the same pattern to any other `plugin-browser` path that
persists bytes, and audit other consumer plugins that bind `ctx.storage` (or
`ctx.memory` / `ctx.vault`) at `on_load` for the same latent bug.

## Secondary hardening: make `plugin-files` a system-tier provider

Independent of the browser fix, the capability **provider** should load before
its consumers. `plugin-files` already self-describes as `category="system"`, but
that field doesn't affect load tier. Set `system_app=True` (or `type=SYSTEM`) on
its manifest so it lands in tier 1 and loads ahead of all USER-tier consumers.
This protects every storage consumer, not just the browser.

(Note: `system_app=True` also means "agent can't function without this" — if
that semantic is too strong, prefer `type=SYSTEM`, or rely on the core-side
capability-ordering fix in the companion proposal.)

## How to verify

1. Provision a fresh agent on the current image.
2. Ask it to screenshot any URL.
3. Expect `screenshot_ref` / `screenshot_url` in the tool result and a
   `browser/screenshot-<id>.png` entry in the Files UI — **no** "No storage
   provider enabled" note.
4. Regression guard: a test that loads `plugin-browser` *before* `plugin-files`
   and asserts a screenshot still persists.
