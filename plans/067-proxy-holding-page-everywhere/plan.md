# 067 — Holding page for every agent page-load failure (no more Cloudflare "Bad gateway")

## Incident

Loading `luna.com.ai/a/vaselin-luna-bug-fixer/` showed Cloudflare's branded
**502 Bad gateway** page (2026-08-01 14:09 UTC). The user should have seen our
own "Luna will be there shortly" page that auto-refreshes until the agent is up.

## What already exists

`cloud/api/proxy.py` already has a self-refreshing holding page
(`_HOLDING_PAGE` + `_holding_page()`, served with **status 200** so Cloudflare
never touches it). It polls `/a/{slug}/__luna_ready` every 3s; the probe
re-triggers a wake on every poll and the page reloads when `{"ready": true}`.

It is returned for browser page navigations (`_is_page_navigation`: GET with
`text/html` in Accept) in exactly two cases:

1. DB status is `stopped`/`error` before proxying (`proxy_to_luna` line ~449).
2. `_proxy_request` raises `ConnectError | ConnectTimeout | ReadTimeout`
   (line ~460).

## The gaps — how a raw 502 still reaches the browser

A page navigation bypasses the holding page and gets a raw 5xx (which
Cloudflare then replaces with its branded page — CF intercepts origin 502/504)
in these cases:

- **Gap A — upstream answers with an HTTP 502/503/504 *response*.** When the
  Fly machine is stopped/suspended/booting, Fly's edge proxy often answers the
  request itself with a 502/503 ("no known healthy instances") instead of
  refusing the connection. `_proxy_request` succeeds (no exception) and line
  ~347/~389 relays `resp.status_code` verbatim. DB still says `running`, so no
  holding-page branch runs. **This is almost certainly the incident.**
- **Gap B — transport errors outside the caught tuple.** `httpx.ReadError`,
  `RemoteProtocolError`, `WriteError`, `PoolTimeout`, `ConnectError` wrapped in
  something else… fall to the generic `except Exception` branch → HTTPException
  502 even for page navigations.
- **Gap C — terminal failures spin forever.** If the machine no longer exists
  or hosting is payment-blocked, the holding page polls `__luna_ready` forever
  with a spinner; the probe never distinguishes "starting" from "will never
  start".

Out of scope (documented so nobody expects this plan to fix it): when
**luna-service itself** is down (Render deploy/crash), the 502 comes from
Render's edge — only a Cloudflare Worker / custom error page can brand that.
Optional phase 2 if it bothers us.

## Design

Rule: **a browser page navigation to `/a/{slug}/...` must never receive a
5xx.** It gets the holding page (200) and the holding page decides what to
show. API/XHR/SSE/asset requests keep JSON error semantics unchanged.

### 1. Gap A — intercept upstream 502/503/504 for page navigations

In `proxy_to_luna`, after `_proxy_request` returns, when
`wants_page and response.status_code in (502, 503, 504)`:

- close/discard the upstream response,
- `_spawn_wake(agent)` (the machine is evidently not serving),
- `record_error_event(kind="proxy_502", severity="warning", …)` with the
  upstream status in context (visibility without paging anyone — the user
  never saw an error),
- return `_holding_page(agent_slug)`.

Implementation note: cleanest as a check in `proxy_to_luna` on the returned
`Response.status_code` — but the HTML branch of `_proxy_request` has already
read the body and the streaming branch hasn't; simplest correct placement is
*inside* `_proxy_request` right after `resp = await client.send(...)`:
`if resp.status_code in (502, 503, 504) and _is_page_navigation(request):
aclose + raise _UpstreamDown(resp.status_code)` and let `proxy_to_luna` catch
it next to the transport-error branch. Luna's own app never legitimately
returns 502/504; a 503 from the app (not Fly) is indistinguishable but the
holding page + reload-when-healthy is the right UX for that too.

### 2. Gap B — broaden the exception net

- Replace the caught tuple with `httpx.TransportError` (superclass of all
  connect/read/write/pool timeouts and protocol errors).
- In the final generic `except Exception` branch: if `wants_page`, log +
  `record_error_event`, `_spawn_wake`, and return `_holding_page(...)` instead
  of raising 502. Non-page requests keep the current 502 JSON.

### 3. Gap C — terminal state on the holding page

Extend `__luna_ready` to return `{"ready": false, "state": "failed",
"detail": "<short reason>"}` when it can tell the wake will never succeed:

- `agent.status == "error"` **and** `_try_wake_agent`-style preconditions fail
  fast (machine gone — `runtime_ref` cleared or `error_message` says
  "Machine no longer exists"), or
- `billing_hosting.hosting_blocked(...)` is true.

Holding-page JS: on `state == "failed"`, stop polling, swap the spinner for
"Luna couldn't start" + the detail + a link to the dashboard. Everything else
keeps `state: "starting"` (absent field = starting, so old cached pages keep
working).

### 4. Optional (decide at review): non-page 502 → 503

Cloudflare also masks 502 JSON bodies for fetch/XHR with its HTML page, which
breaks in-app error handling. Switching the two `HTTP_502_BAD_GATEWAY` raises
to `503 + Retry-After: 5` would dodge CF masking, but changes the API contract
(existing tests assert 502, and luna's chat UI may branch on it). Not required
for the incident; flagging for an explicit yes/no.

## Files

- `cloud/api/proxy.py` — all three gaps (one new sentinel exception class, a
  status check in `_proxy_request`, broadened except branches, `__luna_ready`
  state field, holding-page JS/HTML for the failed state).
- `cloud/tests/test_proxy_wake.py` — extend the existing
  `TestHoldingPage`/`TestLunaReady` classes.

No DB migration. No UI-app changes (holding page is inline HTML).

## Tests

All page-navigation requests send `Accept: text/html`; XHR ones don't.
NB: patch fire-and-forget wake tasks to async no-ops in tests — see
`sqlite-staticpool-test-race` (StaticPool rollback race, plan 066).

1. Page nav, upstream responds **502** (MockTransport returning 502 HTML) →
   200 holding page (`__luna_ready` in body), wake spawned, `proxy_502` event
   recorded with severity warning.
2. Same for upstream **503** and **504**.
3. XHR, upstream 502 → 502 passes through unchanged (contract intact).
4. Page nav, `httpx.RemoteProtocolError` from send → holding page (Gap B).
5. Page nav, arbitrary `RuntimeError` from send → holding page (Gap B generic).
6. `__luna_ready` with machine-gone error state → `{"ready": false,
   "state": "failed", ...}`, and no wake spawned.
7. `__luna_ready` with hosting blocked → `state: "failed"`.
8. Holding-page HTML contains the failed-state handler (string assert on the
   JS, mirroring the existing `__luna_ready` body assert).
9. Regression: SSE/asset/POST requests never get the holding page.

## Verification (prod, after deploy)

1. Stop the bug-fixer agent's machine from the dashboard, then load
   `/a/vaselin-luna-bug-fixer/` in a browser → our holding page, machine wakes,
   page auto-reloads into Luna. No Cloudflare branded page at any point.
2. Error Tracking shows the `proxy_502` warning events with upstream status in
   context (grouped per route).
