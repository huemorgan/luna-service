# 018 · Scenario 02 — Catalog + heads injected into a machine

**Target:** a provisioned Luna machine's env (Fly) and/or the live machine.

## Steps

1. Provision (or update) a test agent from the main image.
2. Inspect the machine's env vars (Fly Machines API `GET /machines/{id}`, or the
   admin machine card if it surfaces env).
3. Confirm:
   - `LUNA_MODEL_CATALOG` is present and is a **valid JSON array**.
   - Every entry has `provider`, `model`, `kinds`; parses against Luna's
     `ModelCatalogEntry` (extra fields ok).
   - `LUNA_PRIMARY_MODEL` and `LUNA_FAST_MODEL` are `provider:model` and **each is a
     member of the injected catalog** with the right kind.
4. Change the reasoning default in the admin Models section, then re-run the
   machine model PATCH (or "push to live"). Re-inspect: `LUNA_PRIMARY_MODEL` and
   `LUNA_MODEL_CATALOG` reflect the change.

## Pass

- `LUNA_MODEL_CATALOG` present, valid JSON, aligned with the admin catalog.
- Heads are in-catalog and correctly typed (primary→reasoning, fast→summarization).
- Live PATCH updates both the heads and the catalog env.

## Fail

- `LUNA_MODEL_CATALOG` missing/empty; a head not in the catalog; brick id
  `claude-sonnet-4-20250514` present anywhere.
