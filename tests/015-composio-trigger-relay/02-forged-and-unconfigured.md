# 02 — Forged signature and unconfigured secret

The ingress is default-deny: wrong signature is rejected, missing secret
means the endpoint effectively doesn't exist.

## Steps

1. With `CLOUD_COMPOSIO_WEBHOOK_SECRET` set on the control plane, run the
   signer with a WRONG secret:
   `python dev/sign_composio_event.py --secret wrong-secret
   --connected-account ca_dojo_alice_001 --url
   http://localhost:8100/api/webhooks/composio`
   → expect HTTP 401.
2. Send a request with no Standard Webhooks headers at all
   (`curl -X POST .../api/webhooks/composio -d '{}'`) → expect 401.
3. Check `GET /api/admin/relay/deliveries` — no new rows from steps 1-2.
4. Restart the control plane with `CLOUD_COMPOSIO_WEBHOOK_SECRET` unset.
   Repeat the valid-format request → expect 403.
5. Restore the secret and restart.

## Pass

- 401 for bad/missing signatures, 403 when no secret configured, zero
  delivery rows created in either case.

## Fail

- Any 2xx, or rows appearing for rejected requests.
