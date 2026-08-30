# 077 — E2E scenarios: hosted playbook delegation card shows live progress

Needs a real hosted tenant with plugin-playbooks ≥ 0.25.3 installed and this
luna-service deployed. Cannot run from a local checkout (no local
control-plane DB/config) — same caveat as plan 062.

## S1 — Live card on a hosted tenant
1. Open `luna.com.ai/a/{slug}` (owner session), ask the agent to delegate a
   playbook run (any playbook).
2. Watch the delegation card in chat.
- PASS: headline progresses past "Starting…" to live phase/step updates
  (phases fill in, "Last step: …" support line, elapsed timer ticking),
  and reaches Done/steps-used without ever showing
  "Working — live updates can't show here" or "Connection lost — retrying".
- Console: zero errors from the card iframe.

## S2 — Poll is sessionless but authorized
1. During S1, copy the card poll URL from the network log
   (`/a/{slug}/api/p/plugin-playbooks/delegations/{id}/card?token=…`).
2. `curl` it with NO cookies: expect 200 JSON status.
3. Same URL with the token altered: expect 404 (from the tenant), not 401.
4. Any other tenant API path without cookies (e.g. `/a/{slug}/api/health`):
   still 401 from the proxy.

## S3 — No wake from an unauthenticated poll
1. Suspend the tenant machine (or pick a stopped agent).
2. `curl` the card URL without cookies: expect 503 quickly.
3. Verify in the service logs / Fly dashboard that no wake was triggered.
