# Plan 011 — Image Cache Warming

## Problem

First-time provisioning takes ~30-60s because Fly pulls the Docker image cold.
With a cached image it's ~6-10s.

## Solution

After promoting an image to main, create a throwaway machine in the image's
configured region to force Fly to cache the image. Track warm status per
image so the admin can see it.

## Implementation

### Phase 1 — Backend

1. Add `cache_warmed_at` (nullable timestamptz) column to `LunaImage` model +
   startup migration.
2. Add `warm_image_cache` method to `FlyMachinesRuntime`:
   - Create a machine with the image in the target region, minimal guest
     (shared-cpu-1x, 256MB), no services, no health checks.
   - Wait for state `started` (confirms image pull complete).
   - Immediately destroy the machine.
   - Return success/failure.
3. Add `POST /api/admin/images/{image_id}/warm-cache` endpoint — manually
   trigger warming. Updates `cache_warmed_at` on success.
4. In `set_main_image`: after promoting, kick off `warm_image_cache` as a
   background task. Update `cache_warmed_at` on completion.

### Phase 2 — Admin UI (Images)

1. On each built image card, show a small indicator:
   - Green dot + "Cache warm" + relative timestamp if `cache_warmed_at` is set.
   - Gray dot + "Cache cold" if null.
2. Add a "Warm Cache" button on cold images (calls the new endpoint).
3. After promote-to-main, the card auto-updates when warming completes.

### Phase 3 — Agent Detail

1. Add `image_version` and `image_cache_warmed_at` to the compute section of
   the agent detail page.
2. Show the image version the agent is running + whether the image was warm
   when provisioned (informational, from the `LunaImage` record).

### Phase 4 — Polish

1. Audit log entry for `image.cache_warmed`.
2. Error handling — if warming fails (e.g. Fly quota), show the error in the
   UI but don't block the promotion.
