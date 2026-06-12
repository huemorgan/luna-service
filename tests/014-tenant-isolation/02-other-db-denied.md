# 02 — Another agent's DB: denied

Run from inside tenant machine A. Target = another agent's DB name
(`luna_a_<other-slug>`), discovered from `SELECT datname FROM pg_database`.

## Steps
1. Build a connect string reusing A's creds but pointing at the other DB name:
   `psql "postgresql://luna_a_<A>:<pw>@<host>/luna_a_<OTHER>" -c "\dt"`

## Pass
- `FATAL: permission denied for database "luna_a_<OTHER>"` (or connection refused).
- No tables from the other tenant are ever returned.

## Fail
- Any successful connection or table listing for a database that isn't A's own.
