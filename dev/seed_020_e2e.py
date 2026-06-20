"""Seed a local admin + sample image for Plan 020 E2E, print a session cookie."""
import asyncio
import json
import os

os.environ.setdefault("CLOUD_SESSION_SECRET", "dev-session-secret")
os.environ.setdefault("CLOUD_DATABASE_URL", "postgresql+asyncpg://luna:luna@localhost:5435/lunaservice")

from itsdangerous import URLSafeTimedSerializer  # noqa: E402
from sqlalchemy import select  # noqa: E402

from cloud.db.session import get_session  # noqa: E402
from cloud.db.models import User, Account, Membership, LunaImage, GatewayModel  # noqa: E402


async def main() -> None:
    async with get_session() as db:
        user = (await db.execute(select(User).where(User.email == "admin@local.test"))).scalar_one_or_none()
        if not user:
            user = User(google_sub="local-admin", email="admin@local.test", name="Local Admin", is_admin=True)
            db.add(user)
            await db.flush()
        user.is_admin = True

        acct = (await db.execute(select(Account).where(Account.slug == "local-admin"))).scalar_one_or_none()
        if not acct:
            acct = Account(slug="local-admin", name="Local Admin", created_by=user.id)
            db.add(acct)
            await db.flush()
            db.add(Membership(account_id=acct.id, user_id=user.id, role="owner"))

        img = (await db.execute(select(LunaImage).where(LunaImage.version == "0.0.0-e2e"))).scalar_one_or_none()
        if not img:
            db.add(LunaImage(
                version="0.0.0-e2e", registry_tag="registry.fly.io/luna-agents:e2e",
                build_status="built", is_main=True, created_by=user.id,
            ))

        nmodels = (await db.execute(select(GatewayModel))).scalars().all()

        await db.commit()
        await db.refresh(user)
        await db.refresh(acct)

    token = URLSafeTimedSerializer(os.environ["CLOUD_SESSION_SECRET"]).dumps(
        json.dumps({"user_id": str(user.id), "account_id": str(acct.id)})
    )
    print("USER_ID", user.id)
    print("MODELS_SEEDED", len(nmodels))
    print("COOKIE", token)


asyncio.run(main())
