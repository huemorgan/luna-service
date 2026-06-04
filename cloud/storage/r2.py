"""Cloudflare R2 helpers — currently read-only stats for the agent detail page.

R2 is provisioned per the phase-004 plan but not yet wired into the runtime,
so most calls degrade gracefully when credentials are missing.
"""

from __future__ import annotations

import logging
import os
from typing import TypedDict

log = logging.getLogger(__name__)


class PrefixStats(TypedDict):
    object_count: int
    size_bytes: int
    configured: bool


def r2_configured() -> bool:
    return bool(
        os.environ.get("R2_ENDPOINT")
        and os.environ.get("R2_ACCESS_KEY")
        and os.environ.get("R2_SECRET_KEY")
        and os.environ.get("R2_BUCKET")
    )


async def list_prefix_stats(prefix: str) -> PrefixStats:
    """Return object_count + total size_bytes for a prefix in the R2 bucket.

    If R2 is not configured, returns zeros with `configured=False` so the UI
    can render a "not yet in use" hint instead of a hard failure.
    """
    if not r2_configured():
        return {"object_count": 0, "size_bytes": 0, "configured": False}

    try:
        # Import inside the function so optional boto3 dep isn't required
        # until R2 is actually configured. Most dev/local environments
        # don't have R2 set up yet.
        import asyncio
        import boto3  # type: ignore
        from botocore.client import Config  # type: ignore
    except ImportError:
        log.info("boto3 not installed; skipping R2 stats")
        return {"object_count": 0, "size_bytes": 0, "configured": False}

    def _sync_list() -> PrefixStats:
        client = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY"],
            aws_secret_access_key=os.environ["R2_SECRET_KEY"],
            config=Config(signature_version="s3v4"),
        )
        bucket = os.environ["R2_BUCKET"]
        paginator = client.get_paginator("list_objects_v2")
        count = 0
        total = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                count += 1
                total += int(obj.get("Size", 0))
        return {"object_count": count, "size_bytes": total, "configured": True}

    try:
        import asyncio
        return await asyncio.to_thread(_sync_list)
    except Exception as exc:  # pragma: no cover — never crash the detail page on R2
        log.warning("R2 stats failed for prefix=%s: %s", prefix, exc)
        return {"object_count": 0, "size_bytes": 0, "configured": False}
