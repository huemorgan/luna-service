"""Plan 019 — bake_plugin_set.py against an offline file:// fixture marketplace.

Drives the real CLI so the Docker bake stage is covered end-to-end with no
network. Verifies: exact-set baking, sha256 fail-closed, lock emission, layout,
and seed fallback.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bake_plugin_set.py"


def _make_artifact(pkg: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{pkg}/__init__.py", "# test plugin\n")
        zf.writestr(f"{pkg}/luna-plugin.toml", f'name = "{pkg}"\nversion = "0.1.0"\n')
    return buf.getvalue()


def _publish(mp_root: Path, name: str, version: str, pkg: str) -> str:
    """Write an artifact into the fixture marketplace; return its sha256."""
    data = _make_artifact(pkg)
    dest = mp_root / "plugins" / name / version / "artifact.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _run(out: Path, *, selection: Path | None = None, seed: Path | None = None,
         marketplace: str | None = None, context: Path | None = None):
    cmd = [sys.executable, str(SCRIPT), "--out", str(out)]
    if selection:
        cmd += ["--selection", str(selection)]
    if seed:
        cmd += ["--seed", str(seed)]
    if marketplace:
        cmd += ["--marketplace", marketplace]
    if context:
        cmd += ["--context", str(context)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_bakes_exact_selection(tmp_path):
    mp = tmp_path / "mp"
    sha_c = _publish(mp, "plugin-charts", "0.1.0", "plugin_charts")
    _publish(mp, "plugin-files", "0.2.0", "plugin_files")  # available but NOT selected

    sel = tmp_path / "plugin-set.json"
    sel.write_text(json.dumps({
        "marketplace": mp.as_uri(),
        "plugins": [{"name": "plugin-charts", "version": "0.1.0", "sha256": sha_c}],
    }))
    out = tmp_path / "out"
    r = _run(out, selection=sel)
    assert r.returncode == 0, r.stderr

    # Exactly one package baked — the selected one.
    assert (out / "plugin_charts" / "__init__.py").exists()
    assert not (out / "plugin_files").exists()

    lock = json.loads((out / "plugin-set.lock.json").read_text())
    assert lock == [{"name": "plugin-charts", "version": "0.1.0", "sha256": sha_c}]


def test_fails_closed_on_sha_mismatch(tmp_path):
    mp = tmp_path / "mp"
    _publish(mp, "plugin-charts", "0.1.0", "plugin_charts")
    sel = tmp_path / "plugin-set.json"
    sel.write_text(json.dumps({
        "marketplace": mp.as_uri(),
        "plugins": [{"name": "plugin-charts", "version": "0.1.0", "sha256": "b" * 64}],
    }))
    out = tmp_path / "out"
    r = _run(out, selection=sel)
    assert r.returncode != 0
    assert "sha256 mismatch" in r.stderr
    assert not (out / "plugin_charts").exists()


def test_seed_fallback_when_no_selection(tmp_path):
    mp = tmp_path / "mp"
    sha_f = _publish(mp, "plugin-files", "0.2.0", "plugin_files")
    seed = tmp_path / "plugin-set.toml"
    seed.write_text(
        f'marketplace = "{mp.as_uri()}"\n\n'
        f'[[plugins]]\nname = "plugin-files"\nversion = "0.2.0"\nsha256 = "{sha_f}"\n'
    )
    out = tmp_path / "out"
    # empty context (no plugin-set.json) → falls back to the explicit seed
    r = _run(out, seed=seed, context=tmp_path / "empty")
    assert r.returncode == 0, r.stderr
    assert (out / "plugin_files" / "__init__.py").exists()


def test_empty_selection_bakes_empty_set(tmp_path):
    sel = tmp_path / "plugin-set.json"
    sel.write_text(json.dumps({"plugins": []}))
    out = tmp_path / "out"
    # empty selection + empty context → nothing to bake, but dir + lock exist
    r = _run(out, selection=sel, context=tmp_path / "empty")
    assert r.returncode == 0, r.stderr
    assert json.loads((out / "plugin-set.lock.json").read_text()) == []


def test_rejects_multi_top_level_artifact(tmp_path):
    mp = tmp_path / "mp"
    # Hand-craft a bad artifact with two top-level dirs.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/__init__.py", "")
        zf.writestr("b/__init__.py", "")
    data = buf.getvalue()
    dest = mp / "plugins" / "plugin-bad" / "0.1.0" / "artifact.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    sel = tmp_path / "plugin-set.json"
    sel.write_text(json.dumps({
        "marketplace": mp.as_uri(),
        "plugins": [{"name": "plugin-bad", "version": "0.1.0", "sha256": sha}],
    }))
    out = tmp_path / "out"
    r = _run(out, selection=sel)
    assert r.returncode != 0
    assert "one top-level dir" in r.stderr
