# S3 — Machine restart no longer invalidates wiki auth

Old behavior: a Fly machine restart rotated `~/.luna/jwt_secret` (ephemeral
HOME), so every token minted before the restart 401'd until a full page reload.
New behavior: the secret comes from the stable per-agent `LUNA_JWT_SECRET` env,
so restarts keep old tokens valid; and even when a token IS stale, the 0.7.1
pane requests a fresh one from the Shell instead of retrying the stale one.

Steps:
1. Open a hosted agent's wiki (e.g. Rayla) — confirm it renders.
2. Restart that agent's Fly machine via the Machines API
   (`POST /v1/apps/luna-agents/machines/<id>/restart`, or stop+start).
3. Wait for the machine health check to go green.
4. WITHOUT reloading the page, click into the Wiki tab again / trigger a
   graph fetch (switch wiki dropdown or navigate away and back to the tab).
5. Screenshot + DOM of the wiki pane.

Pass:
- Wiki fetches succeed after the restart with no full page reload
  (a transient error that self-recovers on the pane's retry is acceptable).

Fail:
- Persistent `-> 401` until the page is manually reloaded.
