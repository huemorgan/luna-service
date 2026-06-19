# 02 — Baked tenant boots with the set (no marketplace, no egress)

**Status:** BLOCKED on Luna `phase08` (the `LUNA_PLUGIN_SET_DIR` loader). The
image bakes the set correctly today, but nothing loads it until phase08 ships in
the image. Run this once an image is built off a Luna release that includes
`discover_plugin_set`.

## Setup
- Build the hosted image (`docker build -f docker/luna-hosted.Dockerfile .`) off a
  Luna version with phase08.
- Provision a fresh local tenant on that image with **no marketplace source
  configured**; block the agent's egress to Render.

## Steps
1. Open the tenant's Settings → Plugins.
2. Confirm `plugin-charts`, `plugin-web-access`, `plugin-files` appear,
   `active`, `source=image-set`.
3. In chat: run a `web_search`, a `file_write`, and render a chart.

## Pass
- All three plugins active from the baked set; all three round-trips succeed with
  zero marketplace contact (verify no outbound fetch in agent logs).

## Evidence → `evidence/`
- `02-plugins-active.png`, `02-chart-rendered.png`, `02-no-egress-logs.txt`
