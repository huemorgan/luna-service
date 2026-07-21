# 050 — jobs-suite findings (scheduler service)

**Status: findings only — no bugs, no fixes required.**

Source: the 10-job dojo suite run 2026-07-20 (Luna v0.41.005), ten fresh
Luna instances each with its own scheduler account on :8123. Full suite
evidence: `luna/dojo/jobs-tests/BUG-SUMMARY.md` in the core repo.

## Verdict: 0 bugs

The scheduler was the most reliable component in the suite:

- 10/10 account provisions via `POST /accounts` succeeded (unique
  account_id + fire_url per instance).
- Trigger registration worked in every test — agents self-created their
  full cadence suites (e.g. test 001: 17 triggers — 5-min uptime playbook,
  3-h setup heartbeat, daily research, nightly dream, weekly review, plus
  per-goal heartbeat/deadline triggers).
- Real fires observed and verified in the scheduler DB (test 001:
  `runs_done=2` within 10 minutes of the 5-min uptime trigger being
  created; test 002: daily renewal-alert trigger registered and scheduled).
- No delivery failures, no duplicate fires, no dead accounts across
  ~4 hours of testing under heavy host load (loadavg peaked ~170).

## Notes (non-bugs, worth considering)

1. **Testability friction:** the per-account admin API requires HMAC
   signing — the admin key alone returns "bad signature", so suite audits
   had to query the scheduler DB directly. Fine for production posture;
   consider a dev-mode read-only inspection endpoint (or a documented
   signing helper script) for dojo runs.
2. **Downstream behavior under agent duplication:** when the agent-side
   bug BUG-L (core repo, `luna/plans/046` Bug 1) creates duplicate goals,
   goalseek registers duplicate heartbeat/deadline triggers with the
   service. The service correctly does what it's told; once the core fix
   lands, no service-side dedup is needed — but if desired, a
   per-account trigger-name uniqueness constraint would be a cheap
   belt-and-braces guard.
