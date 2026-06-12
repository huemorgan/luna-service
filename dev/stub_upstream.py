"""Stub upstream for credential-gateway testing (tests/013-credential-gateway).

Echoes back the auth headers it received so dojo scenarios can prove key
injection / passthrough without calling real providers.

Run:  python dev/stub_upstream.py            (port 9009)
Reject a key:  REJECT_KEYS=real-key-AAA python dev/stub_upstream.py
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("STUB_PORT", "9009"))
REJECT_KEYS = {k.strip() for k in os.environ.get("REJECT_KEYS", "").split(",") if k.strip()}


class EchoHandler(BaseHTTPRequestHandler):
    def _respond(self) -> None:
        auth_headers = {
            name: value
            for name, value in self.headers.items()
            if name.lower() in ("x-api-key", "authorization")
        }
        bare = next(iter(auth_headers.values()), "")
        if bare.lower().startswith("bearer "):
            bare = bare[7:]

        if bare in REJECT_KEYS:
            body = json.dumps({"error": "invalid api key (stub reject)"}).encode()
            self.send_response(401)
        else:
            body = json.dumps({
                "ok": True,
                "path": self.path,
                "method": self.command,
                "received_auth": auth_headers,
            }).encode()
            self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _respond
    do_POST = _respond
    do_PUT = _respond
    do_PATCH = _respond
    do_DELETE = _respond

    def log_message(self, fmt, *args):  # noqa: A002
        print(f"[stub] {self.command} {self.path} :: {fmt % args}")


if __name__ == "__main__":
    print(f"Stub upstream on :{PORT}  (rejecting: {sorted(REJECT_KEYS) or 'nothing'})")
    HTTPServer(("127.0.0.1", PORT), EchoHandler).serve_forever()
