# Note to luna-whatsapp — v0.8.0 base-URL bug (worked around, fix in v0.8.1)

**Date:** 2026-07-05

On real hosted machines `LUNA_GATEWAY_URL` is `"<host>/proxy"` (the
credential-proxy convention), not the control-plane root. Agent-API callers
strip the suffix — see luna `plugins/plugin_vault/gateway.py:106-107`:

    host = base[: -len("/proxy")] if base.endswith("/proxy") else base

`client.control_plane()` in plugin v0.8.0 uses the value as-is, so
auto-provision POSTs `https://<host>/proxy/api/agent/whatsapp/connect`.
Your stub control plane answered there; the real one didn't — auto-provision
silently failed on every real machine.

**Worked around on our side** (deployed): the agent WhatsApp routes are now
also served under `/proxy/...`, so v0.8.0 works unmodified.

**Please still fix in v0.8.1**: strip the `/proxy` suffix like the vault
does, so the plugin follows the platform convention rather than relying on
our alias. No other change needed.
