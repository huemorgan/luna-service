# Scenario 05 — Two users, full isolation

## Preconditions

- Fresh DB
- Stub identity has both Alice and Bob configured

## Scenario

1. Sign in as Alice, wait for provisioning
2. In Alice's chat, send: "Remember that the launch code is BANANA-7."
3. Approve memory write
4. Verify Luna confirms it remembers
5. Sign Alice out
6. Sign in as Bob (different browser profile or incognito to be safe)
7. Wait for Bob's Luna to provision
8. In Bob's chat, send: "What's the launch code?"
9. Observe Bob's Luna response
10. In Bob's chat, send: "Do you know anyone named Alice?"

## Expected Behavior

- Bob gets a **different** Luna container (`luna-bob`)
- Bob's Luna has NO idea about a launch code — responds with something like "I don't have any launch code on file"
- Bob's Luna doesn't recognize Alice or anything Alice said
- DB:
  - 2 rows in `accounts` (alice, bob)
  - 2 rows in `agents` (different schemas, different vault keys, different container names)
  - Tenant DB: 2 schemas (`luna_user_alice`, `luna_user_bob`)
  - Alice's memory row in `luna_user_alice.memories`
  - Bob's `luna_user_bob.memories` does NOT contain "BANANA-7" or anything similar

## Fail Conditions

- ❌ Bob's Luna mentions "BANANA-7" (CATASTROPHIC: data leak)
- ❌ Bob's Luna recognizes Alice
- ❌ Both users routed to same container
- ❌ Both users land in same schema
- ❌ Same vault key for both (means encrypted secrets cross-decryptable — also catastrophic)

## Verify

- `docker ps` shows two containers
- Postgres `\dn` shows both schemas
- Query `luna_user_bob.memories` directly: zero rows containing "BANANA"
- Compare vault keys (visible in container env): must differ
- Screenshot of Bob's response to "what's the launch code?"

## Notes

**This is the most important test in the entire MVP.** If isolation fails, the platform cannot ship. Every other thing can be polish; this is bedrock. Test it again, in production, after every deploy, forever.
