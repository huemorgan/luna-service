# 04 — Retry and recovery

Tenant machines go down; the relay must absorb that and deliver when the
machine returns.

## Steps

1. `docker stop` alice's agent container.
2. Send a valid signed event for alice's connected account → 202.
3. Watch `GET /api/admin/relay/deliveries`: the row stays pending,
   attempts increments, `next_attempt_at` moves out (backoff growing).
4. After 2-3 failed attempts, `docker start` the container and wait for it
   to become healthy plus one backoff interval.
5. Row flips to delivered; container log shows the forwarded request.

## Pass

- No dead-letter for a transient outage; attempts > 1; delivery completes
  after recovery; backoff visibly increases between attempts.

## Fail

- Row dead-letters during a short outage, attempts hammer with no backoff,
  or recovery never delivers.
