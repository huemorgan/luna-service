# Plan 019 — Image-baked plugin set

Bake a curated set of marketplace plugins into every hosted Luna image so each
tenant boots with them already installed — **no marketplace network call at
tenant runtime**. This is the luna-service half of Luna `008.5/phase08`
(`luna/plans/008.5-pluginsdk/phase08-luna-service-update/PLAN.md`).

## Why

Luna `8.5-pluginsdk` removed `charts`, `web_access`, `files` from core; they now
live only in the marketplace. A tenant on this image boots **without** them.
Installing per-tenant at provision is fragile (every machine hits Render Starter
live, no signing). Baking the verified set into the image is reproducible,
offline at runtime, and fails closed at build.

## Dependency: Luna phase08 (core)

This plan assumes the core change from phase08 ships in the image:
- boot discovers a read-only `LUNA_PLUGIN_SET_DIR` and loads each plugin
  (`source=image-set`, lifecycle like in-tree).
Until that lands, baking has no loader to pick the set up. Sequence: phase08
merges to a Luna release → we build an image off it → this plan's bake step
fills the dir. We can land the build plumbing in parallel and flip it on once
the core release is the main image.

## The set is chosen in the luna-service admin UI

**The admin picks which plugins get baked in — not all of them.** The official
marketplace catalog is the menu; the selected subset is the image's baked set.

- Official marketplace root (the only URL we read):
  `https://luna-marketplaces.onrender.com/mp/official/`
- Admin → Images → (an image's) config gets a **Plugin Set** picker: it lists
  the marketplace catalog (`GET {marketplace}/index.json`, proxied through the
  control plane) with a checkbox per plugin and a version. The admin ticks the
  ones to bake. Default selection is a small curated set (charts, web-access,
  files) — **never "all"**.
- The selection persists on the `LunaImage` record as
  `image_config.plugin_set = [{ "name", "version", "sha256" }]` (sha256 captured
  from `index.json` at selection time so the build is pinned and the choice is
  reproducible).

`plugin-set.toml` at repo root is **only the default/seed** for a brand-new
image (and the local-dev fallback); once an image exists, its
`image_config.plugin_set` from the UI is the source of truth the build consumes.

**Scope this round: leaf plugins only** — the picker should mark connectors
(monday/render/cloudflare) as not-yet-bakeable; they carry real PyPI deps and
hit the unresolved dependency-isolation problem (Luna 008.5 §5 / P3). Enforce
in the API (reject non-leaf selections) until that's solved.

## Phases

### A — admin UI: pick the set

- **Catalog proxy** — new admin endpoint `GET /api/admin/marketplace/catalog`
  that fetches `{official}/index.json` server-side and returns
  `[{name, version, description, sha256, bakeable}]` (`bakeable=false` for
  connectors until dep-isolation is solved). Cache briefly (Render Starter cold
  starts).
- **Plugin Set picker** in the image-config admin page (`cloud/ui/.../ImageConfigPage`):
  checkbox list from the catalog, version shown, non-bakeable rows disabled with
  a reason. Default-checks the curated leaf set; saving writes
  `image_config.plugin_set = [{name, version, sha256}]` to the `LunaImage`.
- **API guard** — reject saving a `plugin_set` containing non-bakeable plugins.

### B — bake step in the image build

- New `scripts/bake_plugin_set.py`: resolve the set for the image being built
  from **`image_config.plugin_set`** (the UI selection — fetched by the workflow
  from a control-plane endpoint keyed by `image_id`, or passed as a workflow
  input). Fall back to `plugin-set.toml` only when an image has no selection yet.
  For each entry fetch `{official}/plugins/{name}/{version}/artifact.zip`,
  **verify sha256** against the selection (fail the build on mismatch), unpack
  into `/opt/luna/plugin-set/<pkg>/` (single top-level package dir — the layout
  phase08's `discover_plugin_set` expects). Emit
  `/opt/luna/plugin-set/plugin-set.lock.json` (`[{name,version,sha256}]`) for
  phase08's optional load-time re-verify.
- `docker/luna-hosted.Dockerfile`: builder stage runs the bake script, then
  `COPY --from=… /opt/luna/plugin-set ./plugin-set` (or `/opt/luna/...`), and
  `ENV LUNA_PLUGIN_SET_DIR=/opt/luna/plugin-set`. Put the set dir **outside** any
  per-tenant writable mount so a volume over `~/.luna` can't shadow it.

### D — build-context change (required)

The bake script + `plugin-set.toml` live in luna-service, but the image build
context is currently the `luna/` submodule (`.github/workflows/build-luna-image.yml`
runs `docker build` with `working-directory: luna`). Switch the context to the
**repo root** and rewrite the Dockerfile COPY paths to `luna/…`, so the build
can see `plugin-set.toml` and `scripts/bake_plugin_set.py`. Verify the existing
UI/plugins COPYs still resolve after the context move.

### E — image-config truth fix

`cloud/api/admin_routes.py`:
- `PLUGIN_META` / `DEFAULT_IMAGE_CONFIG.plugins` still present `plugin_web_access`
  and `plugin_files` as if in-tree. Keep their enable toggles (they still get
  `PluginRow`s once loaded from the set) but mark them as **image-set** members
  (e.g. a `source: "image-set"` field in `PLUGIN_META`) so the admin UI is honest
  about where they come from. Add `plugin_charts` to the list.
- Confirm the per-tenant enable/disable path still drives the image-set plugins
  (they load, then the `plugins` toggle governs enabled state like any other).

### F — provisioning sanity

No new env injection needed (the set dir is an image `ENV`, same for all
tenants). Confirm `cloud/provisioning` / runtime don't mount a volume over the
set dir, and that a freshly provisioned tenant comes up with the three plugins
`active`. If a per-tenant volume covers `/opt/luna`, relocate the set dir.

## Decisions

| Topic | Decision |
|---|---|
| Fetch vs vendor artifacts | Fetch pinned artifacts from the official marketplace at build + verify hash (fail closed). Vendoring the zips into the repo is the air-gap fallback if we ever need network-free builds. |
| Where the set dir lives | `/opt/luna/plugin-set`, read-only, outside tenant-writable mounts. |
| Set membership | Admin-selected per image; bakeable list limited to leaf plugins (charts, web-access, files) this round. Connectors wait on dependency isolation. |
| Who owns the list | The admin, via the Plugin Set picker → `image_config.plugin_set`. `plugin-set.toml` is only the default seed / local-dev fallback. |
| Runtime marketplace dependency | none — baked at build; the marketplace is only touched during `docker build`. |

## Definition of done

- Admin can open an image's config, see the marketplace catalog, tick a subset
  (default = leaf set, connectors disabled), save → `image_config.plugin_set`
  persists; non-bakeable selections are rejected.
- A built image bakes **exactly the selected** plugins into
  `/opt/luna/plugin-set/` + `plugin-set.lock.json`, with `LUNA_PLUGIN_SET_DIR`
  set. Picking fewer plugins bakes fewer; nothing forces "all".
- A freshly provisioned tenant (no marketplace source configured, no egress to
  Render) boots with the three plugins `active` `source=image-set`; web_search,
  file_write, and a chart render all work in chat.
- Bake fails the build on any sha256 mismatch.
- Admin image-config no longer claims web-access/files are in-tree.
- Self-host/local (no `LUNA_PLUGIN_SET_DIR`) unaffected.

## Tests (`tests/019-image-plugin-set/`)

- Unit: catalog proxy returns the marketplace list with `bakeable` flags; saving
  `plugin_set` rejects non-bakeable plugins; the picker round-trips into
  `image_config.plugin_set`.
- Unit: `bake_plugin_set.py` bakes exactly the selected set, verifies hashes,
  fails on mismatch, writes the lock, produces the expected dir layout (run
  against a local `file://` fixture marketplace so the test needs no network).
- Build smoke: build the hosted image, assert the set dir + lock + ENV exist.
- Dojo (real browser): provision a local tenant on the baked image with **no
  marketplace added**, confirm charts/web-access/files appear in Settings →
  Plugins and a web_search + file_write + chart round-trip works. Evidence in
  `tests/019-image-plugin-set/evidence/`.
