#!/usr/bin/env bash
# latency-report.sh — p50/p95/max per endpoint from Render edge logs (plan 037-SPEED101).
# Usage: scripts/latency-report.sh [limit]   (default 1000 log lines)
# Requires: render CLI logged in (~/.render/cli.yaml), python3.
set -euo pipefail

SERVICE_ID="${RENDER_SERVICE_ID:-srv-d8g5pd42m8qs73ekk2b0}"
LIMIT="${1:-1000}"

render logs -r "$SERVICE_ID" --limit "$LIMIT" -o json --confirm 2>/dev/null | python3 -c '
import json, re, sys
from collections import defaultdict

# render logs -o json emits concatenated JSON objects, not an array
dec = json.JSONDecoder()
buf = sys.stdin.read()
logs, i = [], 0
while i < len(buf):
    while i < len(buf) and buf[i] in " \n\r\t,[]":
        i += 1
    if i >= len(buf):
        break
    try:
        obj, j = dec.raw_decode(buf, i)
        logs.append(obj)
        i = j
    except ValueError:
        i += 1

def norm(path):
    path = path.split("?")[0]
    path = re.sub(r"/a/[^/]+", "/a/{slug}", path)
    path = re.sub(r"/[0-9a-f]{8}-[0-9a-f-]{27,}", "/{id}", path)
    path = re.sub(r"/\d+(/|$)", r"/{n}\1", path)
    return path

by_path = defaultdict(list)
for entry in logs:
    m = re.search(r"responseTimeMS=(\d+)", entry.get("message", ""))
    if not m:
        continue
    labels = {l["name"]: l["value"] for l in entry.get("labels", [])}
    if labels.get("type") != "request" or "path" not in labels:
        continue
    key = labels.get("method", "?") + " " + norm(labels["path"])
    by_path[key].append(int(m.group(1)))

def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))]

rows = sorted(by_path.items(), key=lambda kv: -pct(kv[1], 0.5))
hdr = ("endpoint", "n", "p50", "p95", "max")
print(f"{hdr[0]:60} {hdr[1]:>5} {hdr[2]:>7} {hdr[3]:>7} {hdr[4]:>7}")
for path, v in rows:
    print(f"{path[:60]:60} {len(v):>5} {pct(v,0.5):>6}ms {pct(v,0.95):>6}ms {max(v):>6}ms")
'
