"""iPhone app sign-in: Google flow → lunacontrol:// hand-off code → PKCE token exchange → X-Luna-Session."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from cloud.api import auth_routes

pytestmark = pytest.mark.asyncio

VERIFIER = "v" * 64


def _challenge(verifier: str = VERIFIER) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


async def _callback_url(http, **params) -> str:
    """Run /auth/login and return where the stub provider sends the browser next."""
    r = await http.get("/auth/login", params=params)
    assert r.status_code == 302
    return r.headers["location"]


async def _run_login(http, **params):
    loc = urlsplit(await _callback_url(http, **params))
    return await http.get(loc.path, params=parse_qs(loc.query))


async def test_web_login_still_sets_cookie_and_goes_to_dashboard(anon_client):
    r = await _run_login(anon_client)
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard"
    assert "luna_session=" in r.headers.get("set-cookie", "")


async def test_ios_login_hands_off_to_app_without_cookie(anon_client):
    r = await _run_login(anon_client, client="ios", challenge=_challenge())
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("lunacontrol://auth?code=")
    assert "set-cookie" not in r.headers


async def test_ios_login_requires_pkce_challenge(anon_client):
    r = await anon_client.get("/auth/login", params={"client": "ios"})
    assert r.status_code == 400


async def test_token_exchange_then_api_with_header(anon_client):
    r = await _run_login(anon_client, client="ios", challenge=_challenge())
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]

    t = await anon_client.post("/auth/mobile/token", json={"code": code, "verifier": VERIFIER})
    assert t.status_code == 200, t.text
    token = t.json()["token"]

    me = await anon_client.get("/api/auth/me", headers={"X-Luna-Session": token})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "alice@novalystrix.ai"

    agents = await anon_client.get("/api/agents", headers={"X-Luna-Session": token})
    assert agents.status_code == 200
    assert agents.json() == []


async def test_wrong_verifier_is_rejected(anon_client):
    r = await _run_login(anon_client, client="ios", challenge=_challenge())
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    t = await anon_client.post("/auth/mobile/token", json={"code": code, "verifier": "x" * 64})
    assert t.status_code == 400


async def test_expired_code_is_rejected(anon_client, monkeypatch):
    r = await _run_login(anon_client, client="ios", challenge=_challenge())
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    monkeypatch.setattr(auth_routes, "HANDOFF_MAX_AGE", -1)
    t = await anon_client.post("/auth/mobile/token", json={"code": code, "verifier": VERIFIER})
    assert t.status_code == 400


async def test_tampered_state_is_rejected(anon_client):
    r = await anon_client.get("/auth/google/callback", params={"code": "stub-alice", "state": "forged"})
    assert r.status_code == 400


async def test_bad_header_token_is_unauthenticated(anon_client):
    r = await anon_client.get("/api/auth/me", headers={"X-Luna-Session": "garbage"})
    assert r.status_code == 401


async def test_restricted_email_gets_clear_error_in_app(anon_client, monkeypatch):
    from fastapi import HTTPException

    def deny(email):
        raise HTTPException(403, "Sign-ups are currently restricted.")

    monkeypatch.setattr(auth_routes, "_enforce_email_allowlist", deny)
    r = await _run_login(anon_client, client="ios", challenge=_challenge())
    assert r.headers["location"] == "lunacontrol://auth?error=restricted"
    w = await _run_login(anon_client)
    assert w.status_code == 403
