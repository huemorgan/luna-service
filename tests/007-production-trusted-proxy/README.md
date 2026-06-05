# Phase 007 — Production Trusted Proxy Auth

Dojo-style scenarios verifying that Luna instances behind the luna-service proxy
skip the login/signup screen entirely. The proxy authenticates users via Google
OAuth, then injects `X-Luna-User` and `X-Luna-Proxy-Secret` headers. Luna must
accept these and auto-issue a JWT.

## Scenarios

| # | Scenario | File |
|---|----------|------|
| 01 | No login screen in production | `01-no-login-screen.md` |
