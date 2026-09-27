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

  # preferred for fleet releases: migrate while retaining the old image
  python scripts/rollout_image.py promote-preserve --version 0.53.000

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


class _JsonReq(_Req):
    """A Request stand-in carrying a JSON body (handlers that read `await request.json()`)."""

    def __init__(self, body: dict):
        self._body = body

    async def json(self) -> dict:
        return self._body


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
    if args.from_version:
        return await _rebake_from(args.from_version, admin)
    res = await ar.rebake_image(_Req(), admin=admin)
    print(json.dumps({k: res.get(k) for k in ("id", "version", "build_status", "registry_tag")},
                     default=str, indent=2))
    print("watch: gh run list --repo huemorgan/luna-service --workflow build-luna-image.yml")
    return 0


async def _rebake_from(base: str, admin) -> int:
    """Same Luna commit as an existing image, current admin plugin defaults: `{base}-rN`.
    For shipping a plugin-set change without also moving the fleet to newer Luna code."""
    from sqlalchemy import select

    from cloud.api import admin_routes as ar
    from cloud.db.models import LunaImage
    from cloud.db.session import get_session

    async with get_session() as db:
        src = (await db.execute(select(LunaImage).where(LunaImage.version == base))).scalar_one_or_none()
        if src is None or not src.git_sha:
            print(f"{base}: no image with a recorded git sha")
            return 2
        taken = set((await db.execute(select(LunaImage.version).where(
            LunaImage.version.like(f"{base}-r%")))).scalars())
        n = 1
        while f"{base}-r{n}" in taken:
            n += 1
        version = f"{base}-r{n}"
        cfg = await ar._default_image_config(db)
        fly_app = src.registry_tag.split("/", 1)[1].rsplit(":", 1)[0]
        img = LunaImage(
            version=version, registry_tag=f"registry.fly.io/{fly_app}:{version}",
            build_status="building", created_by=admin.id, git_branch=src.git_branch,
            git_sha=src.git_sha, sdk_major=src.sdk_major, sdk_min_major=src.sdk_min_major,
            release_notes=f"Rebake of {base} ({src.git_sha[:7]}) with the current plugin set.",
            image_config={"plugin_set": cfg.get("plugin_set", []) or []}, is_main=False,
        )
        db.add(img)
        await db.commit()
        await db.refresh(img)
        await ar._audit(db, action="image.rebake_triggered", actor=admin, actor_ip=None,
                        target=str(img.id), metadata={"version": version, "base_version": base,
                                                      "git_sha": src.git_sha},
                        after_state={"version": version, "build_status": "building"})
        await db.commit()
        image_id = str(img.id)
    await ar._trigger_github_build(image_id, version, src.git_sha, base)
    print(json.dumps({"id": image_id, "version": version, "git_sha": src.git_sha,
                      "plugins": len(cfg.get("plugin_set") or [])}, indent=2))
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


async def cmd_promote_preserve(args) -> int:
    """Make a built image main and migrate machines, retaining image history."""
    from sqlalchemy import select

    from cloud.api import admin_routes as ar
    from cloud.db.models import LunaImage
    from cloud.db.session import get_session

    async with get_session() as db:
        images = (await db.execute(
            select(LunaImage).where(LunaImage.version == args.version)
        )).scalars().all()
        previous = (await db.execute(
            select(LunaImage).where(LunaImage.is_main == True)  # noqa: E712
        )).scalar_one_or_none()
    if len(images) != 1:
        print(f"expected exactly one image for {args.version}, found {len(images)}")
        return 2
    img = images[0]
    if img.build_status != "built":
        print(f"{args.version} is {img.build_status}, not built — nothing promoted")
        return 2

    admin = await _admin()
    promoted = await ar.set_main_image(str(img.id), _Req(), admin=admin)
    exclude = set(args.exclude or [])
    res = await ar._migrate_all_agents(img.version, img.registry_tag, admin, None, exclude_slugs=exclude)
    migrated = {"updated": res["updated"], "errors": res["errors"]}
    if exclude:
        print(f"left on their current image: {sorted(exclude)}")
    async with get_session() as db:
        retained = previous is None or await db.get(LunaImage, previous.id) is not None
    print(json.dumps({
        "promoted": promoted.get("version"),
        "migrated": migrated.get("updated"),
        "errors": migrated.get("errors", []),
        "previous_image": previous.version if previous else None,
        "previous_image_retained": retained,
    }, default=str, indent=2))
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.wait(pending, timeout=args.warm_timeout)
    return 1 if migrated.get("errors") or not retained else 0


async def cmd_canary(args) -> int:
    """Move one agent's machine to a built image (the admin UI's per-machine update)."""
    from sqlalchemy import select

    from cloud.api import admin_routes as ar
    from cloud.db.models import Agent, LunaImage
    from cloud.db.session import get_session

    async with get_session() as db:
        img = (await db.execute(select(LunaImage).where(LunaImage.version == args.version))).scalar_one_or_none()
        agent = (await db.execute(select(Agent).where(Agent.slug == args.slug))).scalar_one_or_none()
    if img is None or img.build_status != "built":
        print(f"{args.version}: no built image")
        return 2
    if agent is None or not agent.runtime_ref:
        print(f"{args.slug}: no agent with a machine")
        return 2
    admin = await _admin()
    res = await ar.update_machine_image(agent.runtime_ref, _JsonReq({"image_id": str(img.id)}), admin=admin)
    print(json.dumps(res, default=str, indent=2))
    return 0


async def cmd_agents(args) -> int:
    """Agents on accounts this person belongs to (to pick a canary)."""
    from sqlalchemy import select

    from cloud.db.models import Agent, Membership, User
    from cloud.db.session import get_session

    async with get_session() as db:
        rows = (await db.execute(
            select(Agent.slug, Agent.name, Agent.status, Agent.image_version, Agent.runtime_ref)
            .join(Membership, Membership.account_id == Agent.account_id)
            .join(User, User.id == Membership.user_id)
            .where(User.email == args.email, Agent.deleted_at.is_(None))
        )).all()
    for slug, name, st, ver, ref in rows:
        print(f"  {slug:<40} {name:<20} {st:<10} {ver or '':<14} {ref or 'no machine'}")
    return 0


async def cmd_feedcheck(args) -> int:
    """luna-control plan 002 / 082: what the chat feed has received from an agent (or all)."""
    from sqlalchemy import func, select

    from cloud.db.models import Agent, ChatEvent, ChatIndexRow
    from cloud.db.session import get_session

    async with get_session() as db:
        q = select(Agent.slug, func.count(ChatEvent.id), func.max(ChatEvent.created_at)).join(
            ChatEvent, ChatEvent.agent_id == Agent.id).group_by(Agent.slug)
        if args.slug:
            q = q.where(Agent.slug == args.slug)
        rows = (await db.execute(q)).all()
        indexed = dict((await db.execute(
            select(Agent.slug, func.count()).join(ChatIndexRow, ChatIndexRow.agent_id == Agent.id)
            .group_by(Agent.slug))).all())
        recent = []
        if args.slug:
            recent = (await db.execute(
                select(ChatEvent.type, ChatEvent.role, ChatEvent.conversation_id, ChatEvent.created_at)
                .join(Agent, Agent.id == ChatEvent.agent_id).where(Agent.slug == args.slug)
                .order_by(ChatEvent.created_at.desc()).limit(15))).all()
    print(f"agents reporting: {len(rows)}")
    for slug, n, last in sorted(rows):
        print(f"  {slug:<40} events={n:<6} chats={indexed.get(slug, 0):<5} last={last}")
    for typ, role, conv, at in recent:
        print(f"  {at}  {typ:<20} {role or '':<10} {conv}")
    return 0


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

    srb = sub.add_parser("rebake", help="non-main sibling image of current Luna main + current defaults")
    srb.add_argument("--from-version", default=None,
                     help="rebake this existing image's Luna commit instead of Luna main (e.g. 0.92.057)")

    sa = sub.add_parser("audit", help="print recent audit_log rows")
    sa.add_argument("--limit", type=int, default=20)

    spr = sub.add_parser("promote", help="make an image main, migrate every machine")
    spr.add_argument("--version", required=True)
    spr.add_argument("--warm-timeout", type=int, default=180)

    spp = sub.add_parser("promote-preserve", help="make main, migrate machines, retain old images")
    spp.add_argument("--version", required=True)
    spp.add_argument("--warm-timeout", type=int, default=180)
    spp.add_argument("--exclude", action="append", metavar="SLUG",
                     help="agent slug to leave on its current image (repeatable)")

    sc = sub.add_parser("canary", help="move one agent's machine to a built image")
    sc.add_argument("--version", required=True)
    sc.add_argument("--slug", required=True)
    sag = sub.add_parser("agents", help="agents on this person's accounts")
    sag.add_argument("--email", required=True)
    sf = sub.add_parser("feedcheck", help="chat feed events received per agent")
    sf.add_argument("--slug")
    sv = sub.add_parser("verify", help="ask Fly what each machine actually runs")
    sv.add_argument("--version", default=None, help="flag machines not on this tag")

    args = p.parse_args()
    return asyncio.run({
        "status": cmd_status, "pin": cmd_pin, "build": cmd_build,
        "rebake": cmd_rebake, "audit": cmd_audit,
        "promote": cmd_promote, "promote-preserve": cmd_promote_preserve,
        "verify": cmd_verify, "canary": cmd_canary, "agents": cmd_agents, "feedcheck": cmd_feedcheck,
    }[args.cmd](args))


if __name__ == "__main__":
    raise SystemExit(main())
