# 07 — Re-provision rotates credentials

Admin / control plane.

## Steps
1. Note the agent's current `LUNA_DATABASE_URL` password (from fly machine env).
2. Re-provision / update the agent (admin action that rebuilds env).
3. Read the machine env again — password should differ.
4. Confirm the machine reconnects and chat history is intact (same DB, new role password).

## Pass
- Password rotated (old != new).
- Old credential no longer works against the DB.
- Machine reconnects with new credential; data intact.

## Fail
- Password unchanged, or machine can't reconnect, or data lost.
