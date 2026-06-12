# 02 — Key pool: add keys, values are write-only

## Preconditions
- Scenario 01 done (service `echo-test` exists)

## Scenario
1. On `/admin/services`, expand the `echo-test` service
2. Add a key: scope **global**, priority **1**, label `echo-main`,
   value `real-key-AAA`
3. Add a second key: scope **global**, priority **2**, label `echo-backup`,
   value `real-key-BBB`
4. Screenshot the key list

## Expected behavior
- Both keys appear in the pool list with label, scope, priority, active
  state, and cooldown state (none)
- The key **values** (`real-key-AAA` / `real-key-BBB`) appear NOWHERE in
  the UI after saving — not in the table, not in the DOM, not in any
  tooltip. Verify by reading the DOM snapshot, not just the screenshot
- A key can be deactivated and reactivated from the list
- The priority is unique per (service, scope) — adding another priority-1
  global key for echo-test is rejected with a clear error

## Fail conditions
- Key value visible anywhere after save
- Duplicate (service, scope, priority) accepted silently
