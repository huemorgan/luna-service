"""Per-tenant vault key derivation using HKDF-SHA256."""

from __future__ import annotations

import hashlib
import hmac


def derive_tenant_vault_key(root_key: bytes, tenant_id: str) -> bytes:
    """Derive a 32-byte tenant vault key from a root key and tenant identifier.

    Uses HKDF-expand with SHA-256. Deterministic: same inputs always produce
    the same output, so re-provisioning recovers the same vault key.
    """
    prk = hmac.new(root_key, tenant_id.encode(), hashlib.sha256).digest()
    info = f"luna-vault-v1:{tenant_id}".encode()
    okm = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
    return okm
