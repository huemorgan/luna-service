"""Seed the local control-plane DB for the 024 dojo and print a session cookie.

Run AFTER the cloud server has started once (so tables + heal-columns exist):
    .venv/bin/python tests/024-upgrade-preview-tray/seed.py

Prints a line `COOKIE <token>` — set it in the browser via
    document.cookie = 'luna_session=<token>; path=/'
to authenticate as the seeded admin without OAuth.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import select

from cloud.auth.session import _serializer
from cloud.db.models import Account, Agent, LunaImage, Membership, User
from cloud.db.session import get_session

FAKE = "http://localhost:9009"
TARGET = "0.17.002"
OLD = "0.16.002"
NOTES = "\n".join([
    "- Cron-style scheduler triggers (beta)",
    "- Installed plugins now survive machine upgrades",
    "- Pre-upgrade compatibility checks",
    "- Faster marketplace search",
    "- Stability and bug fixes",
])

AGENTS = [
    ("Compatible Luna", "dojo-compatible", OLD, f"{FAKE}/ok"),
    ("Needs Updates", "dojo-needs", OLD, f"{FAKE}/changes"),
    ("Blocked Luna", "dojo-blocked", OLD, f"{FAKE}/blocked"),
    ("Old Machine", "dojo-old", OLD, "http://localhost:9099/dead"),
    ("Up To Date", "dojo-uptodate", TARGET, f"{FAKE}/ok"),
]


async def main() -> None:
    async with get_session() as db:
        user = (await db.execute(
            select(User).where(User.email == "vaselin@gmail.com")
        )).scalar_one_or_none()
        if not user:
            user = User(google_sub="dojo-vaselin", email="vaselin@gmail.com",
                        name="Dojo Admin", is_admin=True)
            db.add(user)
            await db.flush()
        else:
            user.is_admin = True

        acct = (await db.execute(
            select(Account).where(Account.slug == "dojo")
        )).scalar_one_or_none()
        if not acct:
            acct = Account(slug="dojo", name="Dojo", created_by=user.id, status="active")
            db.add(acct)
            await db.flush()

        mem = (await db.execute(select(Membership).where(
            Membership.user_id == user.id, Membership.account_id == acct.id,
        ))).scalar_one_or_none()
        if not mem:
            db.add(Membership(account_id=acct.id, user_id=user.id, role="owner", status="active"))

        img = (await db.execute(
            select(LunaImage).where(LunaImage.version == TARGET)
        )).scalar_one_or_none()
        if not img:
            img = LunaImage(version=TARGET, registry_tag=f"registry.fly.io/luna-agents:{TARGET}",
                            build_status="built", created_by=user.id,
                            built_at=datetime.now(timezone.utc))
            db.add(img)
        img.is_main = True
        img.build_status = "built"
        img.sdk_major = 1
        img.sdk_min_major = 1
        img.release_notes = NOTES
        await db.flush()

        for other in (await db.execute(
            select(LunaImage).where(LunaImage.id != img.id, LunaImage.is_main == True)  # noqa: E712
        )).scalars().all():
            other.is_main = False

        for name, slug, ver, url in AGENTS:
            a = (await db.execute(select(Agent).where(Agent.slug == slug))).scalar_one_or_none()
            if not a:
                a = Agent(account_id=acct.id, creator_id=user.id, name=name, slug=slug)
                db.add(a)
            a.account_id = acct.id
            a.name = name
            a.status = "running"
            a.runtime_kind = "fly-machine"
            a.runtime_ref = f"machine-{slug}"
            a.image_version = ver
            a.internal_url = url

        await db.commit()
        token = _serializer().dumps(json.dumps(
            {"user_id": str(user.id), "account_id": str(acct.id)}
        ))
        print("COOKIE", token)


if __name__ == "__main__":
    asyncio.run(main())
