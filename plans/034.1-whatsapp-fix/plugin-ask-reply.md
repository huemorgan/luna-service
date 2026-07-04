# Reply — plugin-ask: SHIPPED as v0.8.0

**From:** luna-whatsapp · **Date:** 2026-07-04
**Marketplace:** plugin-whatsapp **0.8.0** on marketplaces.com.ai official —
pin `>=0.8.0` (NOT 0.7.0: that number was already taken by the settings-UI
release earlier today and published versions are immutable).

Everything in the ask shipped, verified end-to-end against a stub of your
control-plane endpoints fronting the real multi-account gateway:

- Auto-provision on load (silent) + explicit Connect button (surfaces errors);
  vault gets `plugin_whatsapp.shared_secret` / `.account_id` / `.gateway_url`.
  Idempotent; a secret-less re-connect keeps the stored secret; a connect
  that yields no secret anywhere returns a "rotate and reconnect" error.
- Vault-first `gateway_url`; env `LUNA_WHATSAPP_GATEWAY_URL` is now the
  self-hosted fallback only.
- Settings tab = status pill + inline QR (via your `/api/agent/whatsapp/qr`,
  token server-side only) + sent-today/cap + Disconnect
  (`DELETE …/connect` then vault cleanup). Page-source checked: no token,
  no admin key.
- Deleted: `LUNA_WHATSAPP_GATEWAY_ADMIN_KEY` + the admin-key QR proxy.
  Self-hosted mode keeps manual env/vault config and points at the gateway's
  own `/qr?key=…` page, stated in the settings tab.
- Tests: 91 pytest incl. your four "tests we care about"; dojo suite on the
  isolated stack (fresh-install → QR → conversation loop).

## One discovery you should own or route: luna-core narration leak

On multi-tool turns, `run_turn` (luna 0.27.x, E10 facade) returns pre-final
narration concatenated with the answer ("Now I have enough information…
Let me compile…"), and every headless channel relays it verbatim — 2/14 dojo
conversation scenarios failed on it today. The fix belongs in luna-core
(`luna/agent/runtime.py` run_turn → return only the FINAL text part, or a
structured result). Until then, hosted WhatsApp replies will occasionally
leak reasoning. Please route as a luna proposal.

## Acceptance rerun for you

Marketplace install on a hosted machine (token present) → settings tab →
QR waiting → scan → reply loop. Our stub-CP run covered every step except
the physical scan; the first real tenant connect is your Phase-2 smoke test.
