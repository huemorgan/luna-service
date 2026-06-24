# 06 — Mobile legibility

**Goal:** both redesigns are legible on a phone; ASCII diagrams don't break layout.

## Steps
1. Set a mobile viewport (~390px wide).
2. Load `/products/open-source`: terminal hero + ASCII diagram are readable; the
   ASCII diagram scrolls or stacks rather than overflowing the page.
3. Load `/products/marketplace`: warm sections stack to one column; CTA visible.

## Pass
- Both pages legible on mobile; no horizontal page overflow (a contained
  `overflow-x:auto` on ASCII blocks is acceptable).
- Screenshots saved to `screenshots/`.
