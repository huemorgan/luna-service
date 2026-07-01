# Proposal for Luna (core) — order plugin loading by capability, not just `depends_on`

> PROPOSAL written in the luna-service repo. Nothing in `luna/` is touched from
> here. If accepted, the Luna team recreates it inside the Luna project and
> executes it via Luna's own process.
>
> Companion: `luna-plugins-suggestion-screenshot-storage.md` (the plugin-side
> fix for the specific screenshot symptom). This proposal removes the underlying
> class of bug in core so consumers can't get it wrong.

## The problem in one line

A plugin that **consumes** a capability (e.g. `capabilities=["storage"]`) can be
loaded **before** the plugin that **provides** it (`provider="storage"`), so the
consumer sees `ctx.storage is None` at `on_load` and silently degrades.

## Why it happens today

`_topological_sort` (in `luna/luna/plugins/loader.py`) orders plugins by
`(tier, name)` and builds ordering edges **only** from `manifest.depends_on`.
The manifest already has both sides of the contract:

- providers declare `provider="<capability>"`,
- consumers declare `capabilities=["<capability>"]`,

…but the loader ignores `capabilities` when ordering. So two USER-tier plugins
with no explicit `depends_on` are ordered purely alphabetically. Concrete live
example: `plugin-browser` (consumes `storage`) sorts before `plugin-files`
(provides `storage`), so the browser binds a `None` storage provider and
screenshots never persist. See the companion doc for the full trace.

This affects every capability resolved from the provider registry —
`storage`, `memory`, `vault`, and any future one — not just storage.

## Proposed fix — derive ordering edges from capabilities

In `_topological_sort`, before running Kahn's algorithm, add an implicit edge
`provider → consumer` for every advertised capability:

1. Build `providers: dict[capability, list[plugin_name]]` from each manifest's
   `provider` field.
2. For each plugin with `capabilities=[c, ...]`, for each `c` present in
   `providers`, add an edge from each provider of `c` to this plugin (i.e. treat
   it like an implicit `depends_on`, incrementing `in_degree`).
3. Run the existing Kahn's sort unchanged.

Result: a capability's provider is always loaded before any consumer, regardless
of name or tier tie-breaks. Explicit `depends_on` keeps working as-is.

### Edge cases to handle

- **Capability with no provider installed.** Don't raise (unlike a missing
  `depends_on`). The consumer must already degrade gracefully when the
  capability is absent — keep that contract. Just add no edge.
- **Multiple providers of one capability.** Order all of them before the
  consumer. (Registry `register`/`replace` already tolerates re-registration.)
- **Cycles via capabilities.** The existing cycle detector should treat these
  edges identically and report a clear error. A plugin that both provides and
  consumes the same capability must not create a self-edge.
- **Tier interaction.** Capability edges should compose with tiers; a USER
  provider still loads before a USER consumer. Cross-tier stays valid (a USER
  consumer can depend on a SYSTEM/BONDED provider — it already loads later).

## Why this is the right layer

The plugin-side fix (resolve `ctx.storage` at call time) cures the current
symptom, but leaves a foot-gun: any consumer that reads a capability at
`on_load` re-introduces the bug. Encoding the provider→consumer relationship in
the loader makes the manifest's existing `provider` / `capabilities` fields
actually *mean* "load me after my providers," which is what authors already
assume.

## How to verify

- Unit test: two USER plugins, `A` provides `storage`, `B` consumes `storage`,
  with `B`'s name sorting before `A`'s. Assert load order puts `A` before `B`.
- Regression: `plugin-files` + `plugin-browser` on the same agent → screenshot
  persists to Files with no inline-fallback note (independent of any plugin-side
  change).
- Log line `plugin.load_order` shows the provider ahead of the consumer.
