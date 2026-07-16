# Plan 045 — Telegram service page browser scenarios

These scenarios are executed manually with a controlled browser. After every
meaningful action, capture both a screenshot and a DOM snapshot.

## Scenario 1 — Services navigation and route

1. Sign in as an administrator.
2. Open the admin application at desktop width.
3. Find the Services navigation group.
4. Verify Telegram is present, keyboard reachable, and has a distinct icon.
5. Activate Telegram.
6. Verify the URL is `/admin/telegram` and the page heading identifies Telegram
   monitoring.

Pass: the navigation and route work without console errors or a blank page.
Fail: Telegram is absent, inaccessible, routes elsewhere, or crashes.

## Scenario 2 — Unconfigured gateway

1. Run the service without Telegram gateway URL/admin key configuration.
2. Open `/admin/telegram`.
3. Wait through the initial fetch.
4. Inspect the health, webhook, and database cards.
5. Inspect the page DOM for `token`, `bot_token`, `shared_secret`, and the
   gateway admin key field name.

Pass: the page clearly says Telegram is not configured, remains usable, and no
credential fields or values appear in the DOM.
Fail: the page throws, spins forever, implies the gateway is healthy, or renders
credential data.

## Scenario 3 — Healthy monitoring data

1. Configure the backend test fixture or reachable v0.2 gateway with healthy
   stats and at least two accounts.
2. Open `/admin/telegram`.
3. Verify gateway, webhook, and database cards show healthy semantic text.
4. Verify the 24-hour hourly chart contains inbound and outbound series.
5. Verify the per-Luna table joins account IDs to agent names/slugs and shows bot
   identity, status, volume, and recent activity.
6. Wait at least 15 seconds and verify the page refreshes without losing layout
   state.

Pass: current fleet data appears, polling occurs, and no secret is present.
Fail: data is stale after polling, account rows map to the wrong Luna, or secrets
appear.

## Scenario 4 — Degraded gateway states

1. Exercise fixtures for unauthorized and unreachable gateway responses.
2. Reload `/admin/telegram` for each state.
3. Verify the page distinguishes authorization failure from network failure.
4. Verify stale or partial data is not presented as healthy.

Pass: each failure has clear semantic status text and the page remains usable.
Fail: an unhandled error page appears or both failures are mislabeled healthy.

## Scenario 5 — Responsive read-only page

1. Open `/admin/telegram` at desktop width and capture the full page.
2. Resize to a narrow mobile viewport.
3. Verify health cards, chart, and table remain readable without controls
   overlapping.
4. Inspect all inputs and buttons.

Pass: the page is readable at both sizes and contains no token entry/connect UI.
Fail: content becomes unusable or any admin bot-token field exists.

## Scenario 6 — Tenant connect contract

This scenario requires an installed `plugin-telegram`, an authenticated tenant,
and the external multi-account v0.2 gateway.

1. From the plugin settings UI, submit a valid BotFather token once.
2. Observe the tenant request and resulting connected state.
3. Verify the gateway account ID equals the authenticated agent slug.
4. Verify the plugin receives gateway URL, account ID, shared secret, and bot
   metadata once.
5. Reload plugin settings and verify the plaintext token is not displayed or
   returned.
6. Open the admin Telegram page and verify the new account appears read-only.

Pass: provisioning succeeds without Render/env steps and no token is retained in
the browser or luna-service response after the initial request.
Fail: the caller can choose another account ID, the token is rendered later, or
an admin key reaches the tenant.

## Scenario 7 — Isolation and disconnect

1. Authenticate as tenant A and confirm its Telegram status.
2. Attempt status/disconnect requests while supplying tenant B-like account
   identifiers in query/body values.
3. Verify only tenant A's slug is used.
4. Disconnect tenant A through plugin settings.
5. Verify tenant A becomes disconnected and tenant B is unchanged.

Pass: all lifecycle operations are forced to the authenticated slug.
Fail: another tenant's account can be observed or changed.

## Scenario 8 — Exact inbound relay

1. Send a signed gateway fixture containing whitespace and non-ASCII bytes to
   `/api/webhooks/telegram/{agent_slug}/inbound`.
2. Observe the tenant plugin request.
3. Verify byte-for-byte body equality and exact forwarding of
   `x-tg-account`, `x-tg-timestamp`, and `x-tg-signature`.
4. Repeat while the tenant is sleeping and verify the established wake/retry
   behavior.

Pass: bytes and headers are preserved and a sleeping tenant is retried.
Fail: JSON is reserialized, signature headers change, or wake/retry is skipped.

## Evidence record

Record execution results in `TEST-REPORT.md`, including date, environment, each
scenario's pass/fail/blocked state, screenshot paths, DOM observations, and any
external gateway or credential blocker.
