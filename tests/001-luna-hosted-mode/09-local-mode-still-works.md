# Scenario 09 — Local auth mode still works (backward compat)

## Preconditions

- Start a separate Luna container with `LUNA_AUTH_MODE=local` (the original behavior)
- No proxy in front

## Scenario

1. Open Luna's UI directly
2. Verify the original signup screen appears (first-run)
3. Create an account: `luna` / `password123`
4. Verify login succeeds, lands in chat
5. Send a message, get a reply
6. Sign out
7. Sign back in with same credentials
8. Verify history visible

## Expected Behavior

- All original Luna OSS behavior unchanged
- Adding the trusted-proxy feature did NOT break local auth mode

## Fail Conditions

- ❌ Signup screen doesn't appear
- ❌ Login fails
- ❌ Any regression vs. baseline OSS Luna

## Verify

- Screenshots showing the standard local Luna UX
- Confirm with `git diff` on Luna OSS that no changes touch the local-mode code paths (only additive)

## Notes

This is critical for the upstream contribution PR — Luna users who don't use trusted-proxy mode must see zero change in their experience.
