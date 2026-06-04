# 06 — Coming-Soon Cards Render

## Setup
- On `/dashboard/agents/{id}`

## Steps
1. Scroll to "Activity" card
2. Scroll to "Spend" card
3. Take screenshot of each
4. Read DOM for each row

## Expected
- **Activity** card has rows for at least:
  - Messages this month
  - Tool calls
  - Active hours / day
- **Spend** card has rows for at least:
  - LLM cost this month
  - Compute cost (Fly)
  - Storage cost
  - Cost per plugin
  - Cost cap
- Each row shows a "Coming soon" badge or label and references the future phase (e.g. "phase 008")
- Cards visually de-emphasized (greyed) compared to live cards

## Pass criteria
- Both cards present with all listed rows
- Every row clearly labeled as Coming soon
- Tooltip/aria label explains what the metric will be

## Fail criteria
- Card missing
- Rows are blank (no "Coming soon" or label)
- Rows render fake/synthetic numbers (must be obviously a placeholder)
