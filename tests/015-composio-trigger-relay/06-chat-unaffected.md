# 06 — Chat unaffected (live walkthrough)

The plan touches provisioning env for every machine — prove a freshly
provisioned agent still behaves normally.

## Steps

1. Provision (or re-provision) a local agent through the normal flow.
2. Inspect the container env (`docker inspect`):
   `LUNA_COMPOSIO_WEBHOOK_SECRET` present, non-empty, and different from
   another agent's value (per-agent derivation).
3. Open the agent's chat UI through the control plane proxy
   (`/a/{slug}/`), and hold a short real conversation (agent-live-walkthrough
   skill): greeting, one task-ish request, one follow-up that depends on the
   previous turn.
4. Confirm responses stream, history persists on reload, no errors in the
   container log related to the new env var.

## Pass

- Env var present and per-agent; conversation quality and mechanics
  unchanged.

## Fail

- Missing/shared secret value, startup errors, or chat regressions.
