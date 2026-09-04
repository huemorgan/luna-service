#!/usr/bin/env python3
"""Pre-build plugin-inline-code-run's curated venv into the image (Plan 077).

Runs at `docker build` time, AFTER bake_plugin_set.py. Reads the curated
package list from the baked plugin itself (AST parse of
`plugin_inline_code_run/settings.py::CURATED_PACKAGES`) so the venv can never
disagree with the plugin version this image ships, builds the venv at the
exact path the plugin's `venv_manager` derives
(`<out>/curated-<sha256(sorted list)[:12]>/`), and writes the
`.curated-ready.json` marker the plugin checks. The runtime sets
`LUNA_INLINE_CODE_RUN_VENV_DIR=<out>` and the plugin finds a ready venv on
every boot — no PyPI at tenant runtime, restart-proof (Fly rootfs is
ephemeral; only image layers survive).

If the plugin is not in this image's set, exits 0 with an empty out dir (the
plugin then falls back to its scratch-build path — degraded, not broken).
A package that fails to install or import FAILS THE BUILD: an image must not
ship a silently partial venv.

Contract with the plugin (plugin_inline_code_run/venv_manager.py): dir name
`curated-<key>`, key = sha256("\n".join(sorted(packages)))[:12], marker
`.curated-ready.json` = {"packages", "tool", "installed", "failed"}. The bake
stage's python must be the same minor version as the runtime stage's (both
python:3.12-slim today) — a venv is not relocatable across minors.

Usage:
  python bake_code_run_venv.py --set-dir /opt/luna/plugin-set --out /opt/luna/code-run-venvs
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PLUGIN_PKG = "plugin_inline_code_run"
MARKER = ".curated-ready.json"

# Mirrors venv_manager._installed_names' map (identity for unlisted names).
IMPORT_NAMES = {
    "pillow": "PIL", "fpdf2": "fpdf",
    "python-docx": "docx", "python-pptx": "pptx",
    "beautifulsoup4": "bs4", "pyyaml": "yaml",
    "python-dateutil": "dateutil",
}


def _log(msg: str) -> None:
    print(f"[bake-code-run-venv] {msg}", flush=True)


def _find_settings(set_dir: Path) -> Path | None:
    # bake_plugin_set.py unpacks each artifact FLAT: <set-dir>/<pkg>/… (the
    # zip's single top-level dir is the package). The nested pattern is kept
    # for layouts that keep a per-plugin wrapper dir.
    hits = sorted(set_dir.glob(f"{PLUGIN_PKG}/settings.py")) or sorted(
        set_dir.glob(f"*/{PLUGIN_PKG}/settings.py")
    )
    return hits[0] if hits else None


def _curated_packages(settings_py: Path) -> list[str]:
    tree = ast.parse(settings_py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "CURATED_PACKAGES":
                    value = ast.literal_eval(node.value)
                    return [str(p) for p in value]
    raise SystemExit(f"CURATED_PACKAGES not found in {settings_py}")


def _key(packages: list[str]) -> str:
    h = hashlib.sha256(("\n".join(sorted(packages))).encode()).hexdigest()[:12]
    return f"curated-{h}"


def _import_name(pkg: str) -> str:
    canon = pkg.lower().replace("_", "-")
    return IMPORT_NAMES.get(canon, canon.replace("-", "_"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    settings_py = _find_settings(args.set_dir)
    if settings_py is None:
        _log(f"{PLUGIN_PKG} not in the baked plugin set — skipping venv bake")
        return 0

    packages = _curated_packages(settings_py)
    venv_dir = args.out / _key(packages)
    py = venv_dir / "bin" / "python"
    _log(f"packages ({len(packages)}): {', '.join(packages)}")
    _log(f"building {venv_dir}")

    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    subprocess.run(
        [str(py), "-m", "pip", "install", "--no-cache-dir",
         "--disable-pip-version-check", *packages],
        check=True,
    )

    failed = []
    for pkg in packages:
        r = subprocess.run([str(py), "-c", f"import {_import_name(pkg)}"])
        if r.returncode != 0:
            failed.append(pkg)
    if failed:
        _log(f"FAIL: installed but not importable: {failed}")
        return 1

    (venv_dir / MARKER).write_text(json.dumps({
        "packages": packages, "tool": "venv+pip",
        "installed": packages, "failed": [],
    }))
    _log(f"ready: {venv_dir} (marker written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
