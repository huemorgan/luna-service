# Plan 045 test report

Date: 2026-07-16

Environment: isolated worktree on branch `045-telegram-service-page`. Backend
tests used the repository's in-process FastAPI/SQLite fixtures. Browser tests
used the real Vite UI with a local API harness; no production service was
changed.

## Automated verification

- `21 passed in 3.45s`: post-review Telegram contract fixtures and lifecycle
  tests.
- `72 passed in 15.77s`:
  `test_telegram.py`, `test_telegram_agent.py`, and all WhatsApp/Scheduler
  monitoring, relay, and agent-route regression tests.
- `659 passed, 1 skipped in 263.87s`: complete `cloud/tests` suite before the
  contract adapter amendment; the post-amendment focused regressions above
  cover every changed integration surface.
- `npm run build`: passed. Vite emitted only its existing large-chunk warning.
- Edited frontend files:
  `npx eslint src/pages/admin/TelegramPage.tsx
  src/pages/admin/AdminLayout.tsx src/App.tsx` passed.
- Python Telegram modules compiled successfully.
- `git diff --check`: passed.

The repository-wide `npm run lint` is not clean on the base branch. Its initial
run reported 57 problems across existing admin/pricing/billing files. The one
new effect warning in `TelegramPage.tsx` was fixed; the targeted lint above is
clean. Unrelated lint failures were not changed.

Contract fixtures cover canonical and compatibility account metadata, raw
Telegram webhook normalization, canonical and flat stats, derived privacy/group
visibility, fallback message/chat/failure metrics, canonical
`{ok, account, shared_secret}`, 409 `bot_already_connected`, 503 gateway
`PUBLIC_URL` configuration, and credential redaction.

## Browser scenarios

1. **PASS — Services navigation and route.** Desktop DOM showed the Telegram
   link under Services and `/admin/telegram`; refresh is keyboard-accessible.
   Evidence: `plan-045-healthy-desktop.png`,
   `plan-045-healthy-desktop.md`.
2. **PASS — Unconfigured gateway.** The page rendered a stable, credential-free
   "not configured" state with no console errors.
   Evidence: `plan-045-unconfigured.png`.
3. **PASS — Healthy monitoring data.** Health/webhook/database/fleet cards,
   24-hour chart, and two joined Luna rows rendered. Harness logs recorded
   repeated stats/instances requests after the 15-second poll interval.
   Evidence: `plan-045-healthy-desktop.png`.
4. **PASS — Degraded gateway states.** Unauthorized rendered `Degraded` with a
   server-side configuration message; unreachable rendered `Offline`. Neither
   crashed or showed stale healthy data.
   Evidence: `plan-045-unauthorized.png`,
   `plan-045-unreachable.png`.
5. **PASS — Responsive read-only page.** At 390×844 the body remained 390px
   wide, cards stacked, the table scrolled within its container, and the admin
   navigation used an accessible mobile menu. DOM inspection found zero form
   controls and none of `bot_token`, `shared_secret`, `admin_key`, a sample
   gateway key, or a BotFather-token fixture.
   Evidence: `plan-045-healthy-mobile.png`,
   `plan-045-mobile-menu.png`.
6. **BLOCKED — Live tenant connect.** No deployed multi-account v0.2 gateway or
   BotFather token was provided. The expected flow is covered by backend tests,
   not claimed as live verification.
7. **BLOCKED — Live tenant isolation/disconnect.** Requires two real hosted
   tenants and the v0.2 gateway. Slug forcing is covered by backend tests.
8. **PARTIAL — Exact inbound relay.** Exact bytes, all three Telegram headers,
   plugin path, unknown tenant, and wake/retry behavior passed coded tests. A
   real gateway-to-plugin delivery was not available.

## Deployment state

No commit, push, deployment, production environment change, or production
database operation was performed.
