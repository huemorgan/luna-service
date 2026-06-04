# 02 — Identity & Routing Card

## Setup
- On `/dashboard/agents/{id}` for a real agent (use scenario 01 to get there)

## Steps
1. Read the "Identity & Routing" card
2. Note all field values
3. Run `GET /api/agents` and find the matching agent
4. Compare displayed fields with API values

## Expected
The card shows:
- **Slug**: matches `agent.slug`
- **URL**: `<base_url>/a/<slug>/` — clickable, opens in new tab
- **Account**: account name + plan (e.g. "Vaselin's Workspace · free")
- **Created by**: creator email
- **Created at**: human-friendly date

## Pass criteria
- All five fields populated (no "undefined", "null", or empty)
- URL link is clickable and points to the chat
- Values match API response

## Fail criteria
- Any field shows "null", "undefined", empty, or a placeholder
- URL link missing or broken
