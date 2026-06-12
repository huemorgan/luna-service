# 01 — Own DB: full control

Run from inside a tenant machine (`fly ssh console -a luna-agents -s <machine>`).

## Steps
1. `echo $LUNA_DATABASE_URL` — note the DB name and user (should be `luna_a_<slug>`).
2. `psql "$LUNA_DATABASE_URL" -c "\dt"` — list tables.
3. `psql "$LUNA_DATABASE_URL" -c "CREATE TABLE _probe(x int); DROP TABLE _probe;"`

## Pass
- Connects successfully.
- Sees its own Luna tables (conversations, messages, identity, vault_credentials, …).
- CREATE/DROP succeed — the agent owns its database.

## Fail
- Connection refused, or tables from other tenants visible, or permission denied on its own objects.
