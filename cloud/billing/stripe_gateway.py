"""039/007 — Stripe API access, webhook signature verification, and the
payments_enabled derivation.

A thin async wrapper over httpx (no SDK dependency): form-encoded bodies,
basic auth with the secret key, explicit livemode declaration. All Stripe
traffic in the codebase goes through this module; tests inject an
httpx.MockTransport, so nothing here ever hits the network in CI.

The declared CLOUD_STRIPE_LIVEMODE must match the key prefix — a mismatch
fails closed (payments disabled, gateway constructor refuses) so a
misdeployed key can never charge the wrong environment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select

from cloud.config import Settings, get_settings

STRIPE_API_BASE = "https://api.stripe.com"

_TEST_PREFIXES = ("sk_test_", "rk_test_")
_LIVE_PREFIXES = ("sk_live_", "rk_live_")


class StripeError(Exception):
    """A Stripe API error response. `retryable` distinguishes transient
    failures (worker retries) from permanent rejections (dead-letter)."""

    def __init__(self, status_code: int, message: str, code: str | None = None):
        super().__init__(f"stripe {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.code = code

    @property
    def retryable(self) -> bool:
        return self.status_code == 429 or self.status_code >= 500


def key_matches_mode(secret_key: str, livemode: bool) -> bool:
    prefixes = _LIVE_PREFIXES if livemode else _TEST_PREFIXES
    return secret_key.startswith(prefixes)


def stripe_settings_ok(settings: Settings | None = None) -> bool:
    """All Stripe config present and internally consistent. Checkout and
    webhooks both need the full set, so anything missing disables payments."""
    s = settings or get_settings()
    return bool(
        s.stripe_secret_key
        and s.stripe_publishable_key
        and s.stripe_webhook_secret
        and key_matches_mode(s.stripe_secret_key, s.stripe_livemode)
    )


def _flatten(prefix: str, value: Any, out: list[tuple[str, str]]) -> None:
    """Stripe's form encoding: nested dicts/lists become bracket keys,
    e.g. {"line_items": [{"price": p}]} → line_items[0][price]=p."""
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}[{k}]" if prefix else str(k), v, out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, bool):
        out.append((prefix, "true" if value else "false"))
    elif value is not None:
        out.append((prefix, str(value)))


def form_encode(data: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    _flatten("", data, out)
    return out


class StripeGateway:
    """Async Stripe client bound to one mode. Construct via `from_settings`
    (returns None when unconfigured) except in tests."""

    def __init__(
        self,
        secret_key: str,
        livemode: bool,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ):
        if not key_matches_mode(secret_key, livemode):
            raise ValueError("Stripe key prefix does not match declared livemode")
        self.livemode = livemode
        self._client = httpx.AsyncClient(
            base_url=STRIPE_API_BASE,
            auth=(secret_key, ""),
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "StripeGateway | None":
        s = settings or get_settings()
        if not stripe_settings_ok(s):
            return None
        return cls(s.stripe_secret_key, s.stripe_livemode)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        content = None
        if data is not None:
            content = urlencode(form_encode(data))
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        resp = await self._client.request(
            method,
            path,
            content=content,
            headers=headers,
            params=form_encode(params) if params else None,
        )
        try:
            body = resp.json()
        except json.JSONDecodeError:
            raise StripeError(resp.status_code, resp.text[:200])
        if resp.status_code >= 400:
            err = body.get("error") or {}
            raise StripeError(
                resp.status_code, err.get("message", "unknown error"), err.get("code")
            )
        # Objects that carry livemode must match the declared mode.
        if body.get("livemode") is not None and body["livemode"] != self.livemode:
            raise StripeError(409, f"livemode mismatch on {body.get('id')}")
        return body

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post(
        self, path: str, data: dict[str, Any], idempotency_key: str | None = None
    ) -> dict:
        return await self._request("POST", path, data=data, idempotency_key=idempotency_key)


# ── Webhook signatures ───────────────────────────────────────────────────────

def verify_webhook_signature(
    payload: bytes,
    sig_header: str | None,
    secret: str,
    *,
    tolerance_seconds: int = 300,
    now: float | None = None,
) -> bool:
    """Stripe-Signature scheme: `t=<ts>,v1=<hmac>,...` where the HMAC-SHA256
    is over `{t}.{raw body}` with the endpoint secret. Constant-time compare;
    stale timestamps rejected to stop replay."""
    if not sig_header or not secret:
        return False
    timestamp: str | None = None
    candidates: list[str] = []
    for part in sig_header.split(","):
        k, _, v = part.strip().partition("=")
        if k == "t":
            timestamp = v
        elif k == "v1":
            candidates.append(v)
    if not timestamp or not candidates:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    current = now if now is not None else time.time()
    if abs(current - ts) > tolerance_seconds:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, c) for c in candidates)


# ── payments_enabled derivation ──────────────────────────────────────────────

async def payments_enabled_for(db, config: dict, settings: Settings | None = None) -> bool:
    """True only when Stripe settings are complete AND every purchasable
    product in the buyer's catalog has a Price binding for the declared
    mode. A misconfigured deploy degrades to "Coming soon", never to a
    broken checkout button."""
    s = settings or get_settings()
    if not stripe_settings_ok(s):
        return False
    from cloud.billing.models import StripePriceBinding  # circular-import guard

    keys = {p["key"] for p in config.get("products") or []}
    if not keys:
        return False
    bound = set(
        (
            await db.execute(
                select(StripePriceBinding.product_key).where(
                    StripePriceBinding.livemode == s.stripe_livemode
                )
            )
        ).scalars()
    )
    return keys <= bound
