# 018 · Scenario 01 — Models admin: add / edit / toggle / default

**Target:** luna-service admin UI → Services page → Models section.

## Steps

1. Log in as admin, open `/admin` → Services (or wherever the Models section lives).
2. Find the **Models** section. It lists models grouped by provider, each with:
   - provider + model id + label
   - kinds badges (reasoning / summarization / embedding)
   - an **in/out** (enabled) toggle
   - the provider's key count (with a link to add a key)
3. **Read** the seeded catalog. Expect the 007.016-aligned set:
   - anthropic: `claude-opus-4-6`, `claude-sonnet-4-5-20250929`, `claude-haiku-4-5-20251001`
   - openai: `gpt-4o`, `gpt-4o-mini`, `text-embedding-3-small`, `text-embedding-3-large`
   - **No** `o3`, `o4-mini`, `gpt-4-turbo`, `claude-sonnet-4-20250514`, `claude-opus-4-20250514`.
4. **Add** a model: provider `openai`, model `gpt-4.1`, label `GPT-4.1`,
   kinds `[reasoning, summarization]`, alias `gpt41`. Save.
5. **Toggle out** the new model (enabled = false), then back in.
6. **Edit** its label to `GPT 4.1`. Save.
7. **Set default**: in the reasoning-default dropdown pick `claude-opus-4-6`; in the
   summarization-default dropdown pick `claude-haiku-4-5-20251001`.
8. **Delete** the `gpt-4.1` model.

## Pass

- Each action persists across a page reload.
- The seeded list matches step 3 exactly (no stale ids).
- Default dropdowns only offer in-catalog models of the right kind.
- Deleting removes the row; in/out toggle visibly flips state.
- An audit entry exists for create / update / delete (check admin audit log).

## Fail

- Stale ids appear; a default dropdown offers an out-of-catalog or wrong-kind model;
  edits don't persist; no audit trail.
