# 03 — Fewer is fewer (the set is exactly the selection)

**Status:** bake step runnable now; runtime visibility BLOCKED on phase08.

## Steps
1. In an image config, select **only** `plugin-charts`. Save.
2. Build the image (the workflow fetches the selection; locally:
   `curl .../images/{id}/plugin-set -o plugin-set.json` then
   `docker build -f docker/luna-hosted.Dockerfile .`).
3. Inspect the image:
   `docker run --rm --entrypoint sh <img> -c 'ls /opt/luna/plugin-set'`.

## Pass
- Only `plugin_charts` (+ `plugin-set.lock.json`) is baked. web-access/files are
  **absent**. Nothing forces "all".
- A sha256 mismatch (tamper the selection) **fails the build** (covered by
  `scripts/tests/test_bake_plugin_set.py::test_fails_closed_on_sha_mismatch`).
