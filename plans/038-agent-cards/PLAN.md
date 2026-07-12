# 038 — Agent cards redesign (dashboard)

Requested 2026-07-12: nicer agent cards on `/dashboard`.

## Requirements (Roy)

1. Remove the link + cog from the agent name — the card already has a Config button.
2. Condense cards: two per row.
3. Each card gets a color, configurable in the agent's config page.
4. New agents pick a random **vibrant** color at creation.
5. Delete section: copy-to-clipboard icon on the agent name (the delete confirmation asks to
   type the exact name).

## Design

**Storage** — `agents.color TEXT` (hex `#RRGGBB`, nullable; null falls back to a color derived
deterministically from the agent id so existing agents are colorful with no backfill).

- `cloud/db/models.py`: `color: Mapped[str | None]` on `Agent`.
- `cloud/main.py`: add `("color", "TEXT")` to the existing `ALTER TABLE agents ADD COLUMN IF NOT
  EXISTS` list (control plane's migration mechanism).

**Palette** — curated 12-color vibrant palette (`cloud/api/agent_routes.py`,
exported for reuse): amber, orange, rose, pink, fuchsia, violet, indigo, sky, cyan, emerald,
lime, red — high-saturation values that read well on the dark surface.

**API** (`cloud/api/agent_routes.py`)
- `create_agent`: `color=random.choice(PALETTE)`.
- Admin `create_test_agent` (`admin_routes.py`): same.
- `_agent_dict`: include `color` (fallback: palette[hash(id) % 12] when null).
- `PATCH /api/agents/{id}`: `UpdateAgentRequest` becomes `name?: str, color?: str`; validate
  `#RRGGBB`; at least one field required. Rename behavior unchanged.

**UI**
- `Dashboard.tsx`:
  - Agent list `space-y-3` → `grid gap-3 md:grid-cols-2`.
  - Card: 4 px colored left border + low-alpha tint wash of the agent color; name becomes plain
    text (identity name + emoji/avatar kept, dotted-underline Link and inline cog removed).
    Condensed padding; action buttons (Open/Stop/Start/Retry/Config) unchanged, wrap under the
    title row on narrow cards.
- `AgentDetail.tsx` (the config page): "Card color" row — the 12 palette swatches + native color
  input for custom values; saves via the PATCH endpoint.
- `api.ts`: `AgentInfo.color`, `updateAgent` accepts color.

**Tests** — `cloud/tests`: PATCH color happy path + invalid hex 400; create returns a palette
color; `_agent_dict` fallback for null color.

## Verification

- Cloud pytest green, UI build green.
- Browser (prod): cards in 2 columns, colored, name not a link; change a color in config →
  card reflects it; create nothing new needed (test agent creation already covered by admin flow).
