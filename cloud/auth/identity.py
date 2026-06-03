"""Identity provider abstraction — Google OAuth or a stub for dev/test."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol

from authlib.integrations.httpx_client import AsyncOAuth2Client


@dataclass
class UserInfo:
    sub: str
    email: str
    name: str | None = None
    avatar_url: str | None = None


class IdentityProvider(Protocol):
    async def get_authorization_url(self, redirect_uri: str, state: str) -> str: ...
    async def exchange_code(self, code: str, redirect_uri: str) -> UserInfo: ...


class GoogleIdentityProvider:
    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret

    async def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        client = AsyncOAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret,
            redirect_uri=redirect_uri,
            scope="openid email profile",
        )
        url, _ = client.create_authorization_url(self.AUTHORIZE_URL, state=state)
        return url

    async def exchange_code(self, code: str, redirect_uri: str) -> UserInfo:
        client = AsyncOAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret,
            redirect_uri=redirect_uri,
        )
        token = await client.fetch_token(self.TOKEN_URL, code=code)
        resp = await client.get(self.USERINFO_URL)
        resp.raise_for_status()
        data = resp.json()
        return UserInfo(
            sub=data["sub"],
            email=data["email"],
            name=data.get("name"),
            avatar_url=data.get("picture"),
        )


class StubIdentityProvider:
    """Deterministic identity for local dev/testing — no real OAuth."""

    STUB_USERS = {
        "alice": UserInfo(sub="stub-alice-001", email="alice@novalystrix.ai", name="Alice Dev"),
        "bob": UserInfo(sub="stub-bob-002", email="bob@novalystrix.ai", name="Bob Dev"),
    }

    async def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        return f"{redirect_uri}?code=stub-alice&state={state}"

    async def exchange_code(self, code: str, redirect_uri: str) -> UserInfo:
        key = code.replace("stub-", "")
        return self.STUB_USERS.get(key, self.STUB_USERS["alice"])
