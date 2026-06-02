# Scenario 12 — Vault key per-tenant uniqueness

## Preconditions

- Alice and Bob both have running Lunas

## Scenario

1. Inspect Alice's container env: `docker exec luna-alice env | grep LUNA_VAULT`
2. Inspect Bob's container env: `docker exec luna-bob env | grep LUNA_VAULT`
3. Compare the two keys
4. In Alice's Luna, store an encrypted secret (e.g., via the vault plugin: "save my OpenAI key as `sk-test-123`")
5. Query the tenant DB directly: `SELECT * FROM luna_user_alice.secrets`
6. Confirm the value is encrypted (not stored plaintext)
7. Try to decrypt Alice's secret using Bob's vault key (programmatically — use a small Python script)

## Expected Behavior

- Alice's key ≠ Bob's key
- Alice's secret in DB is ciphertext (binary blob, not the plaintext `sk-test-123`)
- Decrypting Alice's ciphertext with Bob's key FAILS (wrong key)
- Decrypting Alice's ciphertext with Alice's key SUCCEEDS

## Fail Conditions

- ❌ Same key in both containers
- ❌ Secret stored plaintext
- ❌ Bob's key can decrypt Alice's secrets (catastrophic)
- ❌ Key visible in any logs / API response

## Verify

- Output of both `env` commands (two different keys)
- Hex/length of both keys (32 bytes each)
- Python script results showing decryption success/failure as expected

## Notes

Even if database isolation fails someday, vault key isolation is the last line of defense — Alice's secrets are uselessly encrypted to anyone but her Luna. This is why per-tenant key derivation is non-negotiable.
