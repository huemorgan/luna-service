#!/usr/bin/env python3
"""Pull all production error events into errors/NNNN-YYYY-MM-DD.md files.

One md file per day (by occurred_at UTC date), numbered so the directory
sorts chronologically (0001- is the oldest day). Idempotent: every written
entry carries an `<!-- id: ... -->` marker and re-runs skip ids already on
disk. Existing file numbers are never changed; new days get the next free
number in date order.

Auth: mints the admin `luna_session` cookie from the live CLOUD_SESSION_SECRET
(fetched via the Render API — local .env session secrets are stale). Needs
RENDER_API_KEY in the environment or in ./.env.

Usage: .venv/bin/python scripts/pull-errors.py [--hours 168]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx

BASE = "https://luna.com.ai"
SERVICE_ID = "srv-d8g5pd42m8qs73ekk2b0"
ADMIN = {
    "user_id": "34c1fbc2-e586-41d4-95d2-38278998a02b",
    "account_id": "08e29b26-913c-4204-b641-fd72f35fd396",
}
ROOT = Path(__file__).resolve().parent.parent
ERRORS_DIR = ROOT / "errors"
ID_RE = re.compile(r"<!-- id: ([0-9a-f-]{36}) -->")
FILE_RE = re.compile(r"^(\d{4})-(\d{4}-\d{2}-\d{2})\.md$")


def render_api_key() -> str:
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        env = ROOT / ".env"
        if env.exists():
            m = re.search(r"^RENDER_API_KEY=(\S+)", env.read_text(), re.M)
            key = m.group(1) if m else None
    if not key:
        sys.exit("RENDER_API_KEY not set (env or .env)")
    return key


def mint_cookie() -> str:
    from itsdangerous import URLSafeTimedSerializer

    r = httpx.get(
        f"https://api.render.com/v1/services/{SERVICE_ID}/env-vars",
        params={"limit": 100},
        headers={"Authorization": f"Bearer {render_api_key()}"},
        timeout=30,
    )
    r.raise_for_status()
    secret = next(
        e["envVar"]["value"] for e in r.json()
        if e["envVar"]["key"] == "CLOUD_SESSION_SECRET"
    )
    return URLSafeTimedSerializer(secret).dumps(json.dumps(ADMIN))


def fetch_all_events(client: httpx.Client, hours: int) -> tuple[list[dict], list[str]]:
    """All raw events reachable through the grouped API, plus coverage notes."""
    groups, offset = [], 0
    while True:
        r = client.get("/api/admin/errors", params={
            "hours": hours, "limit": 500, "offset": offset, "sort": "count",
        })
        r.raise_for_status()
        page = r.json()["groups"]
        groups.extend(page)
        if len(page) < 500:
            break
        offset += 500

    events, notes = [], []
    for g in groups:
        r = client.get(f"/api/admin/errors/{g['fingerprint']}", params={"limit": 200})
        r.raise_for_status()
        evs = r.json()["events"]
        events.extend(evs)
        if g["count"] > len(evs):
            notes.append(
                f"group {g['fingerprint']} has {g['count']} events; "
                f"API returns newest {len(evs)} — oldest not exported"
            )
    return events, notes


def existing_state() -> tuple[dict[str, Path], set[str], int]:
    """(date -> file, ids already on disk, highest used number)."""
    ERRORS_DIR.mkdir(exist_ok=True)
    by_date, ids, max_num = {}, set(), 0
    for f in ERRORS_DIR.iterdir():
        m = FILE_RE.match(f.name)
        if not m:
            continue
        max_num = max(max_num, int(m.group(1)))
        by_date[m.group(2)] = f
        ids.update(ID_RE.findall(f.read_text()))
    return by_date, ids, max_num


def entry_md(e: dict) -> str:
    when = (e.get("occurred_at") or e.get("created_at") or "")[:19].replace("T", " ")
    who = e.get("agent_slug") or e.get("account_slug") or "-"
    lines = [
        f"## {when} UTC — {e['severity'].upper()} — {e.get('kind') or '-'}",
        f"<!-- id: {e['id']} -->",
        f"- source: `{e['source']}` | agent: `{who}` | fingerprint: `{e['fingerprint']}`",
        f"- message: {e.get('message') or '-'}",
    ]
    ctx = e.get("context")
    if ctx:
        lines += ["", "```json", json.dumps(ctx, indent=2, ensure_ascii=False)[:4000], "```"]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=168, help="lookback window (default 1 week, max 2160)")
    args = ap.parse_args()

    cookie = mint_cookie()
    client = httpx.Client(
        base_url=BASE,
        headers={"Origin": BASE},
        cookies={"luna_session": cookie},
        timeout=60,
    )
    events, notes = fetch_all_events(client, args.hours)
    by_date_files, seen_ids, max_num = existing_state()

    new_by_date: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        if e["id"] in seen_ids:
            continue
        day = (e.get("occurred_at") or e.get("created_at"))[:10]
        new_by_date[day].append(e)

    # Assign numbers to unseen dates in chronological order, after existing ones.
    for day in sorted(set(new_by_date) - set(by_date_files)):
        max_num += 1
        by_date_files[day] = ERRORS_DIR / f"{max_num:04d}-{day}.md"

    written = 0
    for day in sorted(new_by_date):
        path = by_date_files[day]
        entries = sorted(new_by_date[day], key=lambda e: e.get("occurred_at") or "")
        chunk = "\n".join(entry_md(e) for e in entries)
        if path.exists():
            path.write_text(path.read_text().rstrip("\n") + "\n\n" + chunk)
        else:
            path.write_text(f"# Errors — {day}\n\n" + chunk)
        written += len(entries)
        print(f"{path.name}: +{len(entries)}")

    print(f"{len(events)} events fetched, {written} new written, "
          f"{len(events) - written} already on disk or duplicate")
    for n in notes:
        print(f"note: {n}")


if __name__ == "__main__":
    main()
