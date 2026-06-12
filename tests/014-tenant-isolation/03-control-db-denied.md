# 03 — Control / shared DB: denied

Run from inside tenant machine A.

## Steps
1. `psql "postgresql://luna_a_<A>:<pw>@<host>/lunatenants" -c "\dt"`
2. `psql "postgresql://luna_a_<A>:<pw>@<host>/postgres" -c "\l"`

## Pass
- Both fail: `permission denied for database` / connection refused.
- The tenant role cannot reach the legacy shared DB or the maintenance DB.

## Fail
- Any read of `lunatenants` public tables or other tenant schemas.
