# 02 — Tabs

## Goal

The expanded card has three tabs: Overview / Settings / Webhooks.

## Steps

1. From scenario 01, expand a card.
2. Confirm the default tab is Overview.
3. Click Settings; confirm the body changes to a "Connectors plugin (Composio)"
   section.
4. Click Webhooks; confirm the body changes to account-links / deliveries
   sections (possibly empty for an agent that has no connections).
5. Click Overview; confirm the original key/value grid + Update button are back.

## Pass

- All three tabs render their distinct contents.
- The active tab is visually highlighted.
- Tabs don't reset state between switches (e.g. radio selection stays).

## Fail

- A tab is missing.
- Switching tabs doesn't change the body.
- Console errors.
