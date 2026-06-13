"""Per-agent Composio relay secret — derived, never stored.

Same HKDF-style construction as cloud/runtime/proxy_secret.py with a
distinct info label, so the relay secret and the trusted-proxy secret are
independent values from the same root.
"""

from __future__ import annotations

import hashlib
import hmac


def derive_relay_secret(root_secret: str, agent_id: str) -> str:
    prk = hmac.new(root_secret.encode(), agent_id.encode(), hashlib.sha256).digest()
    info = f"luna-composio-relay-v1:{agent_id}".encode()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).hexdigest()
