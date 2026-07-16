# S1 — /terms and /privacy render publicly

Steps:
1. Without any session (logged out / fresh client), open
   `https://luna.com.ai/terms`.
2. Confirm the Terms of Service renders: operator Novalystrix, the
   Service vs Open Source split (AGPL-3.0 / Apache-2.0 mentioned), the
   liability cap, and the learn/train license section.
3. Open `https://luna.com.ai/privacy`; confirm it renders and states the
   session-review + model-training use and the "we do not log into your
   accounts" commitment.
4. Confirm the marketing footer links to both pages.

Pass: both pages render publicly with the expected content; footer links work.
Fail: 404, blank SPA route, or auth required.
