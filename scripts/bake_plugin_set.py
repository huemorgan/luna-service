#!/usr/bin/env python3
"""Bake a curated set of marketplace plugins into an image dir (Plan 019).

Runs at `docker build` time. For each selected plugin it fetches the pinned
artifact from the official marketplace, **verifies sha256** (fail-closed),
validates the single-top-level-package layout Luna's loader expects, and unpacks
it into `<out>/<pkg>/`. Emits `<out>/plugin-set.lock.json` for phase08's optional
load-time re-verify.

Source of the set (first non-empty wins):
  1. a UI selection file (`plugin-set.json`) — per-image, written by the build
     workflow from `image_config.plugin_set`.
  2. the seed `plugin-set.toml` at the repo root (default / local-dev fallback).

stdlib only — the Docker bake stage installs nothing. `file://` marketplaces are
supported so tests run offline.

Usage:
  python scripts/bake_plugin_set.py --out /opt/luna/plugin-set
  python scripts/bake_plugin_set.py --out ./out --marketplace file:///tmp/mp/
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_MARKETPLACE = "https://luna-marketplaces.onrender.com/mp/official/"
LOCK_NAME = "plugin-set.lock.json"


def _log(msg: str) -> None:
    print(f"[bake-plugin-set] {msg}", flush=True)


def _fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[bake-plugin-set] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def _fetch(url: str) -> bytes:
    """Fetch bytes from http(s):// or file:// (no third-party deps)."""
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 — pinned URLs, hash-verified
        return resp.read()


def _resolve_set(context: Path, selection: Path | None, seed: Path | None) -> tuple[str | None, list[dict]]:
    """Return (marketplace_or_None, [{name, version, sha256}])."""
    sel = selection or (context / "plugin-set.json")
    if sel.exists():
        try:
            data = json.loads(sel.read_text())
        except Exception as exc:  # noqa: BLE001
            _fail(f"could not parse selection {sel}: {exc}")
        plugins = data.get("plugins") if isinstance(data, dict) else data
        marketplace = data.get("marketplace") if isinstance(data, dict) else None
        if plugins:
            _log(f"using UI selection: {sel} ({len(plugins)} plugins)")
            return marketplace, list(plugins)
        _log(f"selection {sel} is empty — falling back to seed")

    sd = seed or (context / "plugin-set.toml")
    if sd.exists():
        try:
            data = tomllib.loads(sd.read_text())
        except Exception as exc:  # noqa: BLE001
            _fail(f"could not parse seed {sd}: {exc}")
        _log(f"using seed: {sd} ({len(data.get('plugins', []))} plugins)")
        return data.get("marketplace"), list(data.get("plugins", []))

    _log("no selection and no seed — nothing to bake")
    return None, []


def _validate_artifact(zip_bytes: bytes) -> str:
    """Enforce single-top-level-dir + __init__.py + luna-plugin.toml. Returns pkg."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        if not names:
            _fail("artifact zip is empty")
        tops = {n.split("/", 1)[0] for n in names}
        if len(tops) != 1:
            _fail(f"artifact must have exactly one top-level dir, got: {sorted(tops)}")
        top = tops.pop()
        if f"{top}/__init__.py" not in names:
            _fail(f"package '{top}' missing __init__.py")
        if f"{top}/luna-plugin.toml" not in names:
            _fail(f"package '{top}' missing luna-plugin.toml")
        return top


def bake(out: Path, marketplace: str, plugins: list[dict]) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    base = marketplace.rstrip("/")
    locked: list[dict] = []

    for entry in plugins:
        name = (entry.get("name") or "").strip()
        version = (entry.get("version") or "").strip()
        sha = (entry.get("sha256") or "").strip().lower()
        if not (name and version and sha):
            _fail(f"entry needs name/version/sha256: {entry!r}")

        url = f"{base}/plugins/{name}/{version}/artifact.zip"
        _log(f"fetch {name}=={version} <- {url}")
        try:
            data = _fetch(url)
        except Exception as exc:  # noqa: BLE001
            _fail(f"fetch failed for {name}=={version}: {exc}")

        actual = hashlib.sha256(data).hexdigest()
        if actual != sha:
            _fail(f"sha256 mismatch for {name}=={version}: expected {sha}, got {actual}")

        pkg = _validate_artifact(data)
        target = out / pkg
        if target.exists():
            _fail(f"package dir '{pkg}' already baked (duplicate / name clash)")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(out)
        _log(f"  ok -> {target}  (pkg={pkg}, sha256 verified)")
        locked.append({"name": name, "version": version, "sha256": sha})

    lock_path = out / LOCK_NAME
    lock_path.write_text(json.dumps(locked, indent=2) + "\n")
    _log(f"wrote {lock_path} ({len(locked)} plugins)")
    return locked


def main() -> None:
    ap = argparse.ArgumentParser(description="Bake marketplace plugins into an image dir.")
    ap.add_argument("--out", required=True, type=Path, help="output dir (LUNA_PLUGIN_SET_DIR)")
    ap.add_argument("--context", type=Path, default=Path("."), help="dir holding plugin-set.json/.toml")
    ap.add_argument("--marketplace", default=None, help="override marketplace root URL")
    ap.add_argument("--selection", type=Path, default=None, help="explicit selection json path")
    ap.add_argument("--seed", type=Path, default=None, help="explicit seed toml path")
    args = ap.parse_args()

    file_marketplace, plugins = _resolve_set(args.context, args.selection, args.seed)
    marketplace = args.marketplace or file_marketplace or DEFAULT_MARKETPLACE

    if not plugins:
        # Nothing to bake is valid (empty set) — still create the dir + lock so
        # LUNA_PLUGIN_SET_DIR exists and is an honest empty set.
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / LOCK_NAME).write_text("[]\n")
        _log("baked empty set")
        return

    _log(f"marketplace: {marketplace}")
    bake(args.out, marketplace, plugins)
    _log("done")


if __name__ == "__main__":
    main()
