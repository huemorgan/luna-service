# Phase 0 — baseline

Date: 2026-08-27. Executed from a fresh clone of origin/main at `13199f5`
("gateway: browser-use seed/suggestion default to /api/v4").

## Test state before any 076 change

`python -m pytest cloud/tests -q` (Python 3.12.13, fresh venv, `pip install -e ./cloud[dev]`):

```
1 failed, 770 passed, 9 skipped
FAILED cloud/tests/test_billing_stripe_clawback.py::test_refund_of_spent_credits_creates_debt_repaid_by_next_grant
```

The single failure is pre-existing on main and unrelated to this plan (billing/Stripe
clawback). Any later phase must keep the count at exactly this failure or better.

## Environment learnings

- `cloud[dev]` extras are missing two packages the suite needs: `aiosqlite`
  (conftest's in-memory async sqlite engine) and nothing else. Without it, 610
  fixture errors. Installed manually; consider adding to dev extras (not done in
  this plan — out of scope).
- pytest-asyncio 0.25.x works; the initially-installed 1.x also produced the same
  errors (the real cause was aiosqlite), so no pin change is needed.
