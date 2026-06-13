# 01 — Card layout

## Goal

The flat machines table is gone; each agent renders as an expandable card
modeled after the Images page.

## Steps

1. Navigate to `https://luna.com.ai/admin/machines`.
2. Snapshot the DOM and screenshot the page.
3. Click the chevron on one row; confirm it expands and shows tabs.
4. Click the same chevron again; confirm it collapses.

## Pass

- No `<table>` tag containing machines (only data inside the expanded card).
- Each card has: state dot, agent name, agent slug, region, version, short
  machine_id, chevron icon.
- Cards with a config override show a small "override" badge in the header.
- Expand/collapse works.

## Fail

- Old table layout still visible.
- Chevron doesn't toggle.
- Expanded body has no tabs.
