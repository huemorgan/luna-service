# 05 — Cross-machine request forgery

Fly machines share a 6PN private network. Run from inside machine A; target
machine B's private address on :8000.

## Steps
1. From A: `echo $LUNA_TRUSTED_PROXY_SECRET` (A's secret).
2. Find B's 6PN address (e.g. via `dig +short <B-machine-id>.vm.luna-agents.internal` or fly API).
3. Send a request to B's internal API with A's trusted-proxy header:
   `curl -s -o /dev/null -w "%{http_code}" http://[<B-6pn>]:8000/api/... -H "X-Trusted-Proxy-Secret: $A_SECRET"`

## Pass
- B rejects the forged request (401/403) — A's secret is not valid for B.

## Fail
- B accepts the request (200) — shared-secret breach not closed.

## Note
If per-agent proxy secrets are not yet wired, this documents the residual risk
to fix; mark fail and track.
