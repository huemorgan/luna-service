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


def set_session(response: Response, user_id: str, account_id: str) -> None:
    payload = json.dumps({"user_id": user_id, "account_id": account_id})
    token = _serializer().dumps(payload)
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
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=MAX_AGE)
        return json.loads(payload)
    except (BadSignature, json.JSONDecodeError):
        return None


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
