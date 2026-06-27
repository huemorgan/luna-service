# 026 — Plugin key provisioning: E2E scenarios (LLM is the test runner)

Browser target: the admin UI at the running control plane. You drive it, read the
DOM, screenshot, and judge. Backend behaviour is also covered by pytest
(`cloud/tests/test_plugin_catalog.py`), but these scenarios verify the wired UX.

## S1 — Plugin catalog CRUD (admin API + UI)
1. Go to Admin → Defaults. A "Plugin keys" / catalog surface is present.
2. The baked plugins (List A) show one row each with a **Key** control:
   "None" / "Use <service> pool key" / "Configure key…".
3. Bind `plugin-browser` → service `browser-use` (which has ≥1 active key).
   Row badge flips to green **keyed**.
4. Reload — the binding persists.
PASS: binding round-trips; badge reflects key presence.

## S2 — Smart suggestion
1. In List B (Supported plugins), add `plugin-monday`.
2. The "Configure key…" flow is pre-filled from the suggester:
   upstream `https://api.monday.com/v2`, auth `header:Authorization:Bearer`,
   display "monday.com".
3. An unknown plugin slug yields a blank upstream flagged "needs review".
PASS: known slug → correct one-click suggestion; unknown → blank + flag.

## S3 — Membership-driven provisioning (proxy mode)
1. Bind a baked plugin to a service that has an active key (key_mode=proxy).
2. Provision / re-provision an agent on an image whose plugin_set includes it.
3. The agent's machine env contains `LUNA_<SLUG>_BASE_URL` (proxy URL) +
   the lsv1 token, and `LUNA_GATEWAY_URL` + `LUNA_GATEWAY_TOKEN` (026.1 pair).
   It does NOT contain the real upstream key (proxy mode).
PASS: proxy env present, no real key; gateway pair present.

## S4 — Key-gated (no key → not provisioned)
1. Bind a plugin to a service with NO active key.
2. Re-derive the agent's env.
PASS: that service is absent from the env (don't provision a keyless proxy).

## S5 — env-mode fallback (admin opt-in)
1. Bind a plugin with key_mode=env to a service that has an active key.
2. Re-derive env.
PASS: the decrypted real key is injected as the service's env key var
   (machine-scoped); clearly labelled in the UI as compromising the key.
