"""Plan 039 — credits, pricing versions, ledger, and billing workers.

Financial invariants owned by this package:
- 1 credit = $0.01 = 10,000 micro-USD; all financial math is integer-only.
- Double-entry ledger: every posted transaction's postings sum to zero.
- Published pricing versions and posted transactions are immutable.
- Every financial mutation is idempotent (operation ID + canonical request hash).
"""
