"""Image defaults — the single source of truth for the hardcoded base image
config and the admin-editable overlay stored in `app_settings`.

Resolution for any image is:
    DEFAULT_IMAGE_CONFIG  <  stored app_settings["image_defaults"]  <  image's own image_config

Lives here (not in api/admin_routes) so provisioning can resolve the same
defaults without importing the API layer.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import AppSetting

# The admin-stored defaults overlay this base under the singleton key below.
IMAGE_DEFAULTS_KEY = "image_defaults"

DEFAULT_IMAGE_CONFIG = {
    "machine": {
        "cpu_kind": "shared",
        "cpus": 1,
        "memory_mb": 1024,
        "region": "sjc",
    },
    "models": {
        # Plan 018: empty = inherit the catalog default (the model marked
        # recommended_default for its kind). An image may pin primary/fast to
        # override the catalog default; a machine may override the image.
        "primary": {},
        "fast": {},
    },
    "plugins": {
        "plugin_vault": True,
        "plugin_memory": True,
        "plugin_identity": True,
        "plugin_brain": True,
        "plugin_meta": True,
        "plugin_approvals": True,
        "plugin_web": True,
    },
    # Plan 019: marketplace plugins baked into this image. Empty = the UI will
    # pre-select the curated leaf set on first open; the build falls back to
    # plugin-set.toml until an explicit selection is saved.
    "plugin_set": [],
    "env": {},
}


def overlay_config(base: dict, overlay: dict | None) -> dict:
    """Shallow merge with one level of dict-merge (matches image_config shape)."""
    out = {**base}
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


async def get_stored_image_defaults(db: AsyncSession) -> dict:
    """The raw admin-stored overlay (app_settings["image_defaults"]), or {}."""
    row = (await db.execute(
        select(AppSetting).where(AppSetting.key == IMAGE_DEFAULTS_KEY)
    )).scalar_one_or_none()
    return row.value if row and isinstance(row.value, dict) else {}


async def resolved_default_config(db: AsyncSession) -> dict:
    """Base config overlaid with the admin-stored image defaults."""
    return overlay_config(DEFAULT_IMAGE_CONFIG, await get_stored_image_defaults(db))
