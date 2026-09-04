"""Headless fleet rollout — pin plugins, build an image, promote it, migrate machines.

The admin UI is the normal path. This script exists for the headless one: it runs
inside the control-plane service (a Render one-off job on srv-d8g5pd42m8qs73ekk2b0)
and calls the same admin_routes handlers the UI does, so audit rows, the GitHub
build dispatch and the Fly migration all behave identically.

  # what the fleet is on right now, and what a build would bake
  python scripts/rollout_image.py status

  # move a baked plugin pin (repeatable) — do this BEFORE build, because
  # build_image snapshots the defaults into the image record at creation time
  python scripts/rollout_image.py pin \
      --plugin plugin-marketplace-ui --plugin-version 1.1.0 --sha256 0fbca7...

  # create the LunaImage row and dispatch build-luna-image.yml
  python scripts/rollout_image.py build [--branch main] [--version 0.53.000] [--force]

  # flip main, migrate every machine, delete the old main (promote_main does all three)
  python scripts/rollout_image.py promote --version 0.53.000

  # ask Fly what each machine actually runs — the DB is not the oracle
  python scripts/rollout_image.py verify --version 0.53.000

Running it as a Render one-off job (a quoted start command with spaces, quotes
and parens all survive the CLI — verified 2026-07-29):

  render jobs create srv-d8g5pd42m8qs73ekk2b0 --confirm \
      --start-command "python scripts/rollout_image.py promote --version 0.53.000"

Job status is not an oracle for what the script did — read stdout:

  curl -H "Authorization: Bearer $RENDER_KEY" \
    "https://api.render.com/v1/logs?ownerId=<team>&resource=<job-id>&limit=200&direction=backward"

Guard rails:
  - `pin` refuses a plugin_set the API would refuse (_validate_plugin_set).
  - `build` refuses to clobber a version that is already built/building unless
    --force is passed, which deletes the stale row first (a cancelled GitHub run
    leaves the row in `building` forever, and build_image then 409s).
  - `promote` refuses anything but a `built` image, and reports migration errors
    per machine; exit code is non-zero if any machine failed to migrate.
  - Agents with no runtime_ref have no machine to migrate and are reported
    separately, not counted as failures.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


class _Req:
    """Minimal stand-in for the Request the handlers only use for the client IP."""

    headers: dict = {}
    client = None


async def _admin():
    from sqlalchemy import select

    from cloud.db.models import User
    from cloud.db.session import get_session

    async with get_session() as db:
        admin = (await db.execute(
            select(User).where(User.is_admin == True).order_by(User.created_at)  # noqa: E712
        )).scalars().first()
    if not admin:
        raise SystemExit("no admin user in this database")
    return admin


async def _images(limit: int = 5):
    from sqlalchemy import select

    from cloud.db.models import LunaImage
    from cloud.db.session import get_session

    async with get_session() as db:
        return (await db.execute(
            select(LunaImage).order_by(LunaImage.created_at.desc()).limit(limit)
        )).scalars().all()


async def cmd_status(args) -> int:
    from sqlalchemy import select

    from cloud.api import admin_routes as ar
    from cloud.db.models import Agent
    from cloud.db.session import get_session

    async with get_session() as db:
        cfg = await ar._default_image_config(db)
        agents = (await db.execute(select(Agent))).scalars().all()

    print("default plugin_set (what the next build would bake):")
    for e in cfg.get("plugin_set") or []:
        print(f"  {e['name']:<28} {e['version']:<10} {e.get('sha256', '')[:12]}")

    tally = collections.Counter(
        a.image_version if a.runtime_ref else f"{a.image_version} (no machine)" for a in agents
    )
    print("\nagents by image_version:")
    for ver, n in sorted(tally.items()):
        print(f"  {ver}: {n}")

    print("\nimages:")
    for img in await _images():
        print(f"  {img.version:<12} {img.build_status:<9} "
              f"{'MAIN' if img.is_main else '    '} {img.id} {img.build_error or ''}")
    return 0


async def cmd_pin(args) -> int:
    from cloud.api import admin_routes as ar
    from cloud.db.session import get_session

    name = ar._norm_plugin_name(args.plugin)
    async with get_session() as db:
        current = await ar._get_app_setting(db, ar.IMAGE_DEFAULTS_KEY)
        pset = [e for e in ((await ar._default_image_config(db)).get("plugin_set") or [])
                if ar._norm_plugin_name(e.get("name", "")) != name]
        pset.append({"name": name, "version": args.plugin_version, "sha256": args.sha256})
        await ar._set_app_setting(
            db, ar.IMAGE_DEFAULTS_KEY, {**current, "plugin_set": ar._validate_plugin_set(pset)}
        )
        await db.commit()
        cfg = await ar._default_image_config(db)

    pinned = next((e for e in cfg["plugin_set"] if e["name"] == name), None)
    print(f"pinned {json.dumps(pinned)}")
    print("note: existing image records keep their own snapshot — build a new image to bake this")
    return 0


async def cmd_build(args) -> int:
    from sqlalchemy import select

    from cloud.api import admin_routes as ar
    from cloud.db.models import LunaImage
    from cloud.db.session import get_session

    admin = await _admin()
    version = args.version
    if not version and args.branch == "main":
        version = (await ar._fetch_luna_version_from_github())[0]
        print(f"luna main __version__ = {version}")

    if args.force and version:
        async with get_session() as db:
            for stale in (await db.execute(
                select(LunaImage).where(LunaImage.version == version)
            )).scalars().all():
                print(f"--force: dropping {stale.version} ({stale.build_status}) {stale.id}")
                await db.delete(stale)
            await db.commit()

    res = await ar.build_image(_Req(), admin=admin, version=args.version, branch=args.branch)
    print(json.dumps(res, default=str, indent=2))
    baked = [(e.get("name"), e.get("version"))
             for e in ((res.get("image_config") or {}).get("plugin_set") or [])]
    if baked:
        print(f"baked plugin_set: {len(baked)} plugins")
    print("watch: gh run list --repo huemorgan/luna-service --workflow build-luna-image.yml")
    return 0


async def cmd_rebake(args) -> int:
    """Non-main sibling image of the current Luna main version with the current
    admin defaults (POST /images/rebake). Auto-picks the next free `{base}-r{n}`
    tag — the sanctioned path for 'same Luna version, new plugin set/Dockerfile',
    since `build --version {base}-rN` fails the workflow's __version__ check."""
    from cloud.api import admin_routes as ar

    admin = await _admin()
    res = await ar.rebake_image(_Req(), admin=admin)
    print(json.dumps({k: res.get(k) for k in ("id", "version", "build_status", "registry_tag")},
                     default=str, indent=2))
    print("watch: gh run list --repo huemorgan/luna-service --workflow build-luna-image.yml")
    return 0


async def cmd_audit(args) -> int:
    from sqlalchemy import select

    from cloud.db.models import AuditLog
    from cloud.db.session import get_session

    async with get_session() as db:
        rows = (await db.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(args.limit)
        )).scalars().all()
    for r in rows:
        print(f"{str(r.created_at)[:19]} {r.action:<28} actor={str(r.actor_user_id)[:8]} "
              f"ip={r.actor_ip} meta={json.dumps(r.metadata_, default=str)[:160]}")
    return 0


async def cmd_promote(args) -> int:
    from sqlalchemy import select

    from cloud.api import admin_routes as ar
    from cloud.db.models import LunaImage
    from cloud.db.session import get_session

    async with get_session() as db:
        img = (await db.execute(
            select(LunaImage).where(LunaImage.version == args.version)
        )).scalars().all()
    if len(img) != 1:
        print(f"expected exactly one image for {args.version}, found {len(img)}")
        return 2
    img = img[0]
    if img.build_status != "built":
        print(f"{args.version} is {img.build_status}, not built — nothing promoted")
        return 2

    admin = await _admin()
    res = await ar.promote_main(str(img.id), _Req(), admin=admin)
    print(json.dumps(res, default=str, indent=2))
    # promote_main warms the new image in a background task; let it finish.
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.wait(pending, timeout=args.warm_timeout)
    return 1 if res.get("errors") else 0


async def cmd_verify(args) -> int:
    from sqlalchemy import select

    from cloud.db.models import Agent
    from cloud.db.session import get_session
    from cloud.runtime.fly_machines import FlyMachinesRuntime

    async with get_session() as db:
        agents = [(a.slug, a.image_version, a.runtime_ref)
                  for a in (await db.execute(select(Agent))).scalars().all()]

    fly = FlyMachinesRuntime()
    client = fly._get_client()
    tally: collections.Counter = collections.Counter()
    stale = []
    for slug, _ver, ref in agents:
        if not ref:
            tally["no machine"] += 1
            continue
        resp = await client.get(f"/machines/{ref}")
        if resp.status_code != 200:
            tally[f"fly http {resp.status_code}"] += 1
            stale.append((slug, f"http {resp.status_code}", ""))
            continue
        m = resp.json()
        tag = ((m.get("config") or {}).get("image") or "").rsplit(":", 1)[-1]
        tally[f"{tag} ({m.get('state')})"] += 1
        if args.version and tag != args.version:
            stale.append((slug, tag, m.get("state") or ""))

    for slug, tag, state in stale:
        print(f"  stale: {slug} {tag} {state}")
    print("fly machine images:")
    for k, n in sorted(tally.items()):
        print(f"  {k}: {n}")
    return 1 if stale else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="fleet versions, images, default plugin_set")

    sp = sub.add_parser("pin", help="set one baked plugin pin in the image defaults")
    sp.add_argument("--plugin", required=True)
    sp.add_argument("--plugin-version", required=True)
    sp.add_argument("--sha256", required=True)

    sb = sub.add_parser("build", help="create the image record and dispatch the GitHub build")
    sb.add_argument("--branch", default="main")
    sb.add_argument("--version", default=None)
    sb.add_argument("--force", action="store_true",
                    help="delete an existing record for this version first (e.g. a cancelled run)")

    sub.add_parser("rebake", help="non-main sibling image of current Luna main + current defaults")

    sa = sub.add_parser("audit", help="print recent audit_log rows")
    sa.add_argument("--limit", type=int, default=20)

    spr = sub.add_parser("promote", help="make an image main, migrate every machine")
    spr.add_argument("--version", required=True)
    spr.add_argument("--warm-timeout", type=int, default=180)

    sv = sub.add_parser("verify", help="ask Fly what each machine actually runs")
    sv.add_argument("--version", default=None, help="flag machines not on this tag")

    args = p.parse_args()
    return asyncio.run({
        "status": cmd_status, "pin": cmd_pin, "build": cmd_build,
        "rebake": cmd_rebake, "audit": cmd_audit,
        "promote": cmd_promote, "verify": cmd_verify,
    }[args.cmd](args))


if __name__ == "__main__":
    raise SystemExit(main())
