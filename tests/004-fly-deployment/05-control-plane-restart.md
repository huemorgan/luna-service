# Scenario 05 — Control plane restart resilience

## Preconditions

- Production deployed
- A real user (Alice) actively chatting

## Scenario

1. Have Alice's browser open with active chat
2. From Render dashboard, manually restart the control plane service
3. During restart (~30s typically), observe Alice's browser
4. Once back, have Alice send a message

## Expected Behavior

- During restart: Alice's existing in-flight SSE stream may interrupt (acceptable)
- After restart: Alice's session is preserved (cookie-based, server-side decode just works)
- New message succeeds without re-login
- Alice's Luna Machine on Fly was unaffected (it's independent)
- No data lost

## Fail Conditions

- ❌ Alice forced to re-login after control plane restart
- ❌ Conversation history disappears
- ❌ Long downtime (> 1 minute)
- ❌ Stale connections to Fly cause issues after restart

## Verify

- Render deploy logs show clean restart
- Alice's browser network tab shows the interruption + recovery
- Session cookie still valid post-restart

## Notes

Control planes get deployed multiple times a day. Each deploy is a restart. Users shouldn't notice.
