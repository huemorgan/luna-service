# 01 — Open Detail from Dashboard

## Setup
- Browser at `/dashboard` (signed in)
- At least one agent in the list (create one if empty: "Test Agent")

## Steps
1. Take screenshot of dashboard
2. Click on the agent's **name** (or the row body, whichever the spec ships)
3. Wait for navigation
4. Take screenshot

## Expected
- URL changes to `/dashboard/agents/{agent_id}` (UUID form)
- Page renders within ~1 s with the agent name in the header
- Header shows breadcrumb-like trail: `Dashboard › <Agent Name>`

## Pass criteria
- URL pattern matches `^/dashboard/agents/[0-9a-f-]{36}$`
- Agent name visible in the heading
- No console errors

## Fail criteria
- 404 or blank page
- Click did nothing
- Navigated to `/a/<slug>/` (the chat) instead of the detail page
