"""Fake tenant Luna for the 024 dojo.

Stands in for a running Luna 0.17 instance so the control-plane upgrade-check can
render every verdict path without real Fly machines. One process, one port; the
verdict is chosen by the URL prefix the control plane calls
(`internal_url` = http://localhost:9009/<ok|changes|blocked|old>).

Run: python tests/024-upgrade-preview-tray/fake_tenant.py
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9009

OK = {
    "target": {"luna_version": "0.17.002", "sdk_major": 1, "sdk_min_major": 1},
    "verdict": "ok",
    "summary": {"compatible": 2, "baked": 1, "needs_upgrade": 0, "unsupported": 0, "unknown": 0},
    "plugins": [
        {"name": "plugin-giphy", "installed_version": "0.1.2", "sdk_major": 1, "status": "compatible"},
        {"name": "plugin-weather", "installed_version": "0.3.0", "sdk_major": 1, "status": "compatible"},
        {"name": "plugin-charts", "installed_version": "1.0.0", "sdk_major": 1, "status": "baked"},
    ],
}

CHANGES = {
    "target": {"luna_version": "0.17.002", "sdk_major": 1, "sdk_min_major": 1},
    "verdict": "upgrade_with_changes",
    "summary": {"compatible": 1, "baked": 1, "needs_upgrade": 2, "unsupported": 0, "unknown": 0},
    "plugins": [
        {"name": "plugin-giphy", "installed_version": "0.1.2", "sdk_major": 1, "status": "compatible"},
        {"name": "plugin-charts", "installed_version": "1.0.0", "sdk_major": 1, "status": "baked"},
        {"name": "plugin-foo", "installed_version": "1.0.0", "sdk_major": 0, "status": "needs_upgrade",
         "upgrade_to": "2.0.0", "marketplace_url": "https://marketplaces.com.ai",
         "reason": "built for SDK v0 (dropped in target); v2.0.0 targets SDK v1"},
        {"name": "plugin-bar", "installed_version": "0.9.0", "sdk_major": 0, "status": "needs_upgrade",
         "upgrade_to": "1.4.0", "marketplace_url": "https://marketplaces.com.ai",
         "reason": "newer compatible version available"},
    ],
}

BLOCKED = {
    "target": {"luna_version": "0.17.002", "sdk_major": 1, "sdk_min_major": 1},
    "verdict": "blocked",
    "summary": {"compatible": 2, "baked": 0, "needs_upgrade": 0, "unsupported": 1, "unknown": 0},
    "plugins": [
        {"name": "plugin-giphy", "installed_version": "0.1.2", "sdk_major": 1, "status": "compatible"},
        {"name": "plugin-weather", "installed_version": "0.3.0", "sdk_major": 1, "status": "compatible"},
        {"name": "plugin-legacy", "installed_version": "1.0.0", "sdk_major": 0, "status": "unsupported",
         "reason": "requires SDK v0; target supports v1+; no compatible version in its marketplace"},
    ],
}

REPORTS = {"ok": OK, "changes": CHANGES, "blocked": BLOCKED}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        # consume body
        length = int(self.headers.get("content-length", 0) or 0)
        if length:
            self.rfile.read(length)
        path = self.path
        if path.endswith("/api/plugins/upgrade-check"):
            prefix = path.split("/api/")[0].strip("/")  # ok | changes | blocked | old
            if prefix == "old":
                self._send(404, {"detail": "Not Found"})
                return
            self._send(200, REPORTS.get(prefix, OK))
            return
        if path.endswith("/api/p/plugin-marketplace/upgrade"):
            self._send(200, {"ok": True})
            return
        self._send(404, {"detail": "Not Found"})

    def do_GET(self):
        self._send(200, {"ok": True, "fake_tenant": True})


if __name__ == "__main__":
    print(f"fake tenant on :{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
