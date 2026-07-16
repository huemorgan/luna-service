# S2 — Signup consent: pre-checked box, gated continue, recorded server-side

Steps:
1. Logged out, open luna.com.ai and click "Start free".
2. Confirm a consent step appears with a checkbox CHECKED BY DEFAULT reading
   "I agree to the Terms of Service and Privacy Policy" (both linked), and a
   "Continue with Google" button.
3. Uncheck the box — the continue button must disable.
4. Re-check and continue; complete Google sign-in (vaselin account).
5. In the prod DB (read-only), confirm the user row has `tos_accepted_at`
   set and `tos_version` equal to the current terms version.

Pass: consent step shown (checked by default), gating works, acceptance
recorded with version + timestamp.
Fail: no consent step, continue works while unchecked, or DB fields empty.
