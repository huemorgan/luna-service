# Plan 009 — GitHub Version Check

## Problem

The admin panel's "Check for Updates" reads the Luna version from
`cloud/.luna-version` on disk. On Render, this file is baked into the
deploy artifact and only changes when someone manually updates the
submodule pointer and pushes. The result: the button always reports
"Up to date" even when a newer Luna version exists upstream.

## Solution

Replace `_read_luna_version()` with a GitHub API call that fetches
`luna/__init__.py` from the `main` branch of `huemorgan/luna` and
parses `__version__` from the live source.

## Implementation

### Phase 1 — Backend

Replace the `_read_luna_version()` function in `cloud/api/admin_routes.py`:

1. Use `httpx.AsyncClient` to `GET https://api.github.com/repos/huemorgan/luna/contents/luna/__init__.py?ref=main`
2. Decode the Base64 `content` field from the response
3. Parse `__version__ = "X.Y.Z"` from the decoded text
4. Cache the result for 5 minutes (in-memory) to avoid rate limits
5. Fall back to `cloud/.luna-version` on disk if the API call fails
6. No GitHub token required — the repo is public

### Phase 2 — Update unit tests

Update `test_check_update` and `test_check_update_no_update` in
`cloud/tests/test_admin.py` to mock the new GitHub fetch instead
of the old `_read_luna_version` function.

## Out of scope

- Authenticated GitHub API (public repo, 60 req/hr unauthenticated is plenty)
- Webhooks or push-based notification of new versions
