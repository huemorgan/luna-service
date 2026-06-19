# Results — 019 image-baked plugin set

Branch: `019-image-plugin-set`. luna-service side of Luna `008.5/phase08`.

## What shipped (all luna-service-side phases)

- **Phase A — pick the set.** `GET /api/admin/marketplace/catalog` (server-side
  proxy of the official `index.json`, 120s cached, fails soft); `plugin_set` on
  the image config with server-side validation (leaf-only, name/version/sha256
  required, dupes rejected); a **Plugin Set** picker in `ImageConfigPage` that
  reads the catalog, disables connectors, default-checks the curated leaf set,
  and writes `image_config.plugin_set`.
- **Phase B — bake step.** `scripts/bake_plugin_set.py` (stdlib only) fetches
  pinned artifacts, **sha256-verifies fail-closed**, validates the single-pkg
  layout, unpacks to `/opt/luna/plugin-set/<pkg>/`, writes `plugin-set.lock.json`.
  `plugin-set.toml` seeds the curated leaf set with real pinned hashes.
- **Phase C/D — build context.** Dockerfile moved to a **repo-root context**
  (`docker build -f docker/luna-hosted.Dockerfile .`), all `luna/…` COPYs
  rewritten, new `plugin-set` build stage + `ENV LUNA_PLUGIN_SET_DIR`, a
  per-Dockerfile `.dockerignore` so it coexists with the control-plane build, and
  the workflow now fetches the per-image selection before building.
- **Phase E — honesty.** `PLUGIN_META` carries `source`; web-access/files/charts
  are `image-set`, and `plugin_charts` was added.
- **Phase F — provisioning.** No change needed: neither the Fly create payload
  (no `mounts`) nor docker-local (`docker run` has no `-v`) mounts over
  `/opt/luna`, so the set dir can't be shadowed. `LUNA_PLUGIN_SET_DIR` rides the
  image ENV — no per-tenant injection.

## Verification

| Check | Result |
|---|---|
| `cloud/tests/test_plugin_set.py` (catalog, validation, round-trip, resolve, honesty) | **17 pass** |
| `scripts/tests/test_bake_plugin_set.py` (exact set, sha fail-closed, seed fallback, layout) | **5 pass** |
| Full cloud suite | **141 pass, 1 skip** |
| UI typecheck + vite build | clean |
| Bake stage build (live marketplace) | charts/web-access/files fetched + **sha verified**, lock written |
| Full hosted image build | clean; `LUNA_PLUGIN_SET_DIR=/opt/luna/plugin-set`, set dir + lock + `ui/dist` + `luna/` all present |

### Incidental fix
The cloud test harness was 401-ing the **entire** admin suite (31 tests across
untouched files): modules that did `from cloud.config import get_settings` bound
the original lru-cached function, so the autouse `cloud.config.get_settings`
patch never reached them and the server verified cookies/webhook secrets with the
default dev secrets. Fixed `conftest._patch_settings` to also drive the real
`get_settings` via env + cache-clear. This unbroke the 31 pre-existing failures.

## Gated on Luna phase08 (cannot pass yet)

- **`02-baked-tenant-boots.md`** and the runtime half of `03-fewer-is-fewer.md`:
  the image bakes the set correctly, but Luna's `discover_plugin_set` loader
  (phase08, in the `luna` submodule) must ship in the image before a tenant loads
  them at boot. Sequence: phase08 → Luna release → build an image off it → these
  pass.

## Recommended manual check (runnable now)

- `01-pick-the-set.md`: bring up the local control plane and click through the
  Plugin Set picker (catalog renders, connectors disabled, selection persists).
  Covered functionally by unit tests; a browser pass is the last visual confirm.
