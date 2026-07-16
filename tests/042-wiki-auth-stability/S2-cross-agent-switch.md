# S2 — Cross-agent switch does not poison the wiki token

This is the historical trigger: `localStorage['luna.token']` on luna.com.ai is
origin-wide, so opening agent A used to leave a token that agent B's wiki pane
picked up and retried forever.

Steps:
1. In one browser session, open agent A's shell (e.g. Rayla) and use it
   (open its Wiki tab, let it authenticate).
2. Without clearing storage or reloading, navigate to agent B's wiki
   (`/a/vaselin-starla/p/wiki`).
3. Screenshot + DOM of B's wiki pane.
4. Navigate back to A's wiki; screenshot + DOM again.

Pass:
- Both agents' wiki panes render content; neither shows `-> 401`.

Fail:
- Either pane shows the 401 error after switching agents.
