# Scenario 08 — Schema-scoped DB connection works

## Preconditions

- Postgres has TWO test schemas created: `luna_test_alice` and `luna_test_bob`
- TWO Luna containers running with different `LUNA_DB_SCHEMA` envs:
  - `local-luna-app-alice` with `LUNA_DB_SCHEMA=luna_test_alice` on port 8001
  - `local-luna-app-bob` with `LUNA_DB_SCHEMA=luna_test_bob` on port 8002

## Scenario

1. Open `http://localhost:8001` (with proxy headers for alice)
2. Send: "My secret pet name is Whiskers."
3. Wait for response
4. Open `http://localhost:8002` (with proxy headers for bob)
5. Send: "What's my pet's name?"
6. Wait for response

Then verify via Postgres directly:
```sql
SELECT count(*) FROM luna_test_alice.messages;
SELECT count(*) FROM luna_test_bob.messages;
```

## Expected Behavior

- Alice's Luna confirms (or stores) the pet name
- Bob's Luna has NO idea what pet — completely unaware
- `luna_test_alice.messages` count > 0
- `luna_test_bob.messages` count > 0 (just bob's question + reply)
- Bob has zero rows in alice's schema, and vice versa
- Tables in `public` schema either don't exist or are empty (everything writes to the tenant schema)

## Fail Conditions

- ❌ Bob's Luna mentions Whiskers (catastrophic data leak)
- ❌ Both Lunas' messages land in the same schema
- ❌ Migrations created tables in `public` schema instead of the tenant schema
- ❌ Either container fails to start because schema doesn't exist (means schema check failed gracefully — that's actually OK but should produce a clear error)

## Verify

- Live `psql` query results for both schemas
- DOM of bob's chat showing he has no idea about Whiskers
- Container logs for both Lunas show their respective schema in startup banner

## Notes

This is the **isolation foundation** for the whole platform. Get this wrong and every user sees every other user's data. Critical to verify.
