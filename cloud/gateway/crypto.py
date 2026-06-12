"""AES-GCM encryption for pool keys, derived from CLOUD_VAULT_ROOT_KEY."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cloud.config import get_settings

_INFO = b"luna-gateway-keys-v1"


def _gateway_key() -> bytes:
    """Derive a dedicated 32-byte key so pool-key encryption is domain-separated
    from tenant vault keys (same HKDF-expand pattern as cloud/vault/keygen.py)."""
    root = bytes.fromhex(get_settings().vault_root_key)
    prk = hmac.new(root, _INFO, hashlib.sha256).digest()
    return hmac.new(prk, _INFO + b"\x01", hashlib.sha256).digest()


def encrypt_key(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_gateway_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_key(token: str) -> str:
    raw = base64.b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_gateway_key()).decrypt(nonce, ct, None).decode()
