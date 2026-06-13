"""Standard Webhooks (https://www.standardwebhooks.com/) sign + verify.

Composio signs its deliveries with this convention; the relay verifies them
at the edge and re-signs forwarded events with the tenant's relay secret.
Same scheme both hops — the secret is the entire interface.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

SIGNED_HEADERS = ("webhook-id", "webhook-timestamp", "webhook-signature")
DEFAULT_TOLERANCE_S = 300


class WebhookAuthError(Exception):
    """Raised on any verification failure. Message is safe to log (no secrets)."""


def _raw_secret(secret: str) -> bytes:
    # Standard Webhooks secrets are often prefixed "whsec_" + base64 payload.
    if secret.startswith("whsec_"):
        try:
            return base64.b64decode(secret[len("whsec_"):])
        except Exception:
            pass
    return secret.encode()


def sign(*, secret: str, webhook_id: str, timestamp: int | None = None, body: bytes) -> dict[str, str]:
    """Produce the three Standard Webhooks headers for an outgoing delivery."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    to_sign = f"{webhook_id}.{ts}.".encode() + body
    digest = hmac.new(_raw_secret(secret), to_sign, hashlib.sha256).digest()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": ts,
        "webhook-signature": "v1," + base64.b64encode(digest).decode(),
    }


def verify(
    *,
    secret: str,
    webhook_id: str,
    timestamp: str,
    raw_body: bytes,
    signature_header: str,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
) -> None:
    """Raise WebhookAuthError unless the delivery verifies. Constant-time compares."""
    if not webhook_id or not timestamp or not signature_header:
        raise WebhookAuthError("missing_headers")

    try:
        ts = int(timestamp)
    except ValueError:
        raise WebhookAuthError("bad_timestamp")
    now = int(time.time())
    if abs(now - ts) > tolerance_s:
        raise WebhookAuthError("timestamp_out_of_window")

    to_sign = f"{webhook_id}.{timestamp}.".encode() + raw_body
    expected = hmac.new(_raw_secret(secret), to_sign, hashlib.sha256).digest()

    for candidate in signature_header.split():
        sig = candidate.split(",", 1)[1] if "," in candidate else candidate
        try:
            decoded = base64.b64decode(sig)
        except Exception:
            continue
        if hmac.compare_digest(expected, decoded):
            return
    raise WebhookAuthError("signature_mismatch")
