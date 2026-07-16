# S1 — Wiki tab loads on hosted agents (no 401)

Precondition: cloud deployed with per-agent LUNA_JWT_SECRET, fleet backfilled,
plugin-wiki 0.7.1 installed on the target agents.

Steps:
1. Log in to https://luna.com.ai as vaselin (or mint a `luna_session` cookie).
2. Open `https://luna.com.ai/a/<rayla-slug>/p/wiki`.
3. Wait for the pane iframe to finish loading (a few seconds).
4. Screenshot + read the DOM inside the wiki area.
5. Repeat 2–4 for Starla (`/a/vaselin-starla/p/wiki`).

Pass:
- The wiki graph (or empty-wiki state) renders.
- No red `Error: GET /graph?wiki=main -> 401` text anywhere in the pane.

Fail:
- Any `-> 401` error text, or a perpetually blank/erroring pane.
