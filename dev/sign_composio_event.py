"""Sign a Composio-style webhook event and POST it — dev/dojo harness.

Plays the role of Composio cloud for local testing of the trigger relay
(plan 015). Also documents what self-hosters' deliveries look like.

Usage:
  python dev/sign_composio_event.py \
      --secret test-composio-secret \
      --connected-account ca_dojo_alice_001 \
      --url http://localhost:8100/api/webhooks/composio

Options:
  --webhook-id ID    delivery id (default: random msg_…)
  --skew SECONDS     offset the signed timestamp (test replay window)
  --payload FILE     JSON file to send instead of the built-in sample
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cloud.relay.standard_webhooks import sign  # noqa: E402


def sample_payload(connected_account: str) -> dict:
    return {
        "type": "gmail_new_gmail_message",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE",
            "connected_account_id": connected_account,
            "app_name": "gmail",
            "payload": {
                "subject": "Dojo test event",
                "sender": "dojo@example.com",
                "snippet": "This is a relay test delivery.",
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret", required=True)
    parser.add_argument("--connected-account", default="ca_dojo_test_001")
    parser.add_argument("--url", default="http://localhost:8100/api/webhooks/composio")
    parser.add_argument("--webhook-id", default=None)
    parser.add_argument("--skew", type=int, default=0)
    parser.add_argument("--payload", default=None)
    args = parser.parse_args()

    if args.payload:
        body = Path(args.payload).read_bytes()
    else:
        body = json.dumps(sample_payload(args.connected_account)).encode()

    webhook_id = args.webhook_id or f"msg_{uuid.uuid4().hex[:20]}"
    headers = sign(
        secret=args.secret,
        webhook_id=webhook_id,
        timestamp=int(time.time()) + args.skew,
        body=body,
    )
    headers["content-type"] = "application/json"

    resp = httpx.post(args.url, content=body, headers=headers, timeout=15)
    print(f"webhook-id: {webhook_id}")
    print(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return 0 if resp.status_code < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
