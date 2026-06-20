# 02 — Edit image defaults

## Steps
1. Go to `/admin/images/defaults`.
2. Change the **primary model** default to a different enabled catalog model; save.
3. In the **default plugin set**, remove one plugin and add one via search; save.
4. Hard-reload the page.

## Expect
- Model dropdowns list enabled catalog models (reasoning for primary, etc.).
- Saving shows a success state (no error toast).
- After reload, the changed model + plugin set persist (read from the server,
  not local state).
- A brand-new / unconfigured image's config reflects these defaults (spot check
  in `GET /api/admin/images/{id}/config` for an image with empty `image_config`,
  or open an image config page and confirm the inherited default).

## Pass/Fail
PASS if edits persist across reload and the resolver surfaces them as the
inherited default for images without an explicit override.
