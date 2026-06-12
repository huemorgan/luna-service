# 06 — Normal operation after migration

Browser, as the agent owner.

## Steps
1. Open `https://luna.com.ai/a/<slug>/`.
2. Send a chat message; wait for a reply.
3. Admin → Services → Usage: confirm the request was metered for this agent.
4. Restart the machine (fly), reopen chat, confirm prior conversation persists.

## Pass
- Agent replies normally (LLM call routed through gateway).
- Usage row appears/increments for the agent (billable).
- Conversation history survives restart — data is in the agent's own DB.

## Fail
- Chat hangs, 401 from gateway, no usage recorded, or history lost.
