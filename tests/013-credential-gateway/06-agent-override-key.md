# 06 — Agent-scoped override beats global, for that agent only

## Preconditions
- Scenarios 01–03 done; two test agents A and B with tenant tokens

## Scenario
1. In the admin services UI, add a key to `echo-test` with scope
   **agent:A**, priority 1, label `echo-A-dedicated`, value `real-key-CCC`
2. `curl` the proxy with agent A's token; read echoed headers
3. `curl` the proxy with agent B's token; read echoed headers

## Expected behavior
- Agent A's request reaches the stub with `real-key-CCC` (the override)
- Agent B's request reaches the stub with `real-key-AAA` (global
  priority-1; or BBB if 04's cooldown is still active)
- Usage events attribute each request to the right agent and key
- The override key is injected proxy-side: nothing about `real-key-CCC`
  is visible to the caller in any response header/body

## Fail conditions
- Override applies to the wrong agent or to all agents
- Override key value leaks to the caller
