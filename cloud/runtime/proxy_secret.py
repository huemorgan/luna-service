"""Per-agent trusted-proxy secret derivation.

Fly machines in one app share a private 6PN network: any machine can reach
any other machine's :8000 directly. A single shared secret means malicious
code on machine A holds the credential machine B trusts. We derive a distinct
secret per agent from the root secret so a forged cross-machine request fails.

Deterministic (HKDF-style HMAC-SHA256): the control plane recomputes the same
value when proxying, so nothing is stored.
"""

from __future__ import annotations

import hashlib
import hmac


def derive_proxy_secret(root_secret: str, agent_id: str) -> str:
    """Derive an agent-specific trusted-proxy secret from the root secret."""
    prk = hmac.new(root_secret.encode(), agent_id.encode(), hashlib.sha256).digest()
    info = f"luna-proxy-v1:{agent_id}".encode()
    okm = hmac.new(prk, info + b"\x01", hashlib.sha256).hexdigest()
    return okm


def derive_jwt_secret(root_secret: str, agent_id: str) -> str:
    """Derive an agent-specific LUNA_JWT_SECRET from the root secret.

    Plan 042: Fly machines have an ephemeral HOME, so Luna's fallback of
    persisting a random JWT secret on disk rotates on every restart and
    invalidates all outstanding tokens. Injecting this stable derived value
    keeps tokens valid across restarts while staying distinct per agent —
    and distinct from the proxy/relay derivations via the info string.
    """
    prk = hmac.new(root_secret.encode(), agent_id.encode(), hashlib.sha256).digest()
    info = f"luna-jwt-v1:{agent_id}".encode()
    okm = hmac.new(prk, info + b"\x01", hashlib.sha256).hexdigest()
    return okm
