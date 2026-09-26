"""Signed session cookie using itsdangerous."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from cloud.config import get_settings

COOKIE_NAME = "luna_session"
MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret)


HEADER_NAME = "x-luna-session"  # the iPhone app sends its session here instead of a cookie


def make_session_token(user_id: str, account_id: str) -> str:
    """The signed value the cookie carries; the iPhone app holds the same value."""
    return _serializer().dumps(json.dumps({"user_id": user_id, "account_id": account_id}))


def set_session(response: Response, user_id: str, account_id: str) -> None:
    token = make_session_token(user_id, account_id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=get_settings().env != "dev",
        path="/",
    )


def get_session(request: Request) -> dict | None:
    # Cookie first (web); else the app's header. Same signature, same max age.
    token = request.cookies.get(COOKIE_NAME) or request.headers.get(HEADER_NAME)
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=MAX_AGE)
        return json.loads(payload)
    except (BadSignature, json.JSONDecodeError):
        return None


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
