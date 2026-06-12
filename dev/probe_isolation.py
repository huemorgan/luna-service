import asyncio, os, re, asyncpg

URL = os.environ["LUNA_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
m = re.match(r"postgresql://([^:]+):([^@]+)@([^/]+)/(.+)", URL)
user, pw, host, db = m.groups()
host = host.split("?")[0]; db = db.split("?")[0]

async def conn(target_db):
    return await asyncpg.connect(user=user, password=pw, host=host, database=target_db, ssl="require", timeout=15)

async def main():
    print("== 01 own DB control ==")
    c = await conn(db)
    await c.execute("CREATE TABLE _probe(x int)"); await c.execute("DROP TABLE _probe")
    tabs = await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")
    print("  own tables:", len(tabs), "create/drop=OK")
    print("== 04 catalog ==")
    dbnames = [r["datname"] for r in await c.fetch("SELECT datname FROM pg_database WHERE datname LIKE 'luna_a_%'")]
    print("  visible luna_a_ db names:", len(dbnames))
    foreign = await c.fetch("SELECT schemaname,tablename FROM pg_tables WHERE schemaname LIKE 'luna_user_%'")
    print("  foreign luna_user_ tables visible:", len(foreign))
    await c.close()

    print("== 02 other agent DB ==")
    other = next((n for n in dbnames if n != db), None)
    if other:
        try:
            c2 = await conn(other); await c2.execute("SELECT 1"); await c2.close()
            print(f"  BREACH: connected to {other}")
        except Exception as e:
            print(f"  denied ({other}):", str(e)[:80])
    else:
        print("  (no other db name visible)")

    print("== 03 control/shared DB ==")
    for target in ("lunatenants", "postgres"):
        try:
            c3 = await conn(target); await c3.execute("SELECT 1"); await c3.close()
            print(f"  BREACH: connected to {target}")
        except Exception as e:
            print(f"  denied ({target}):", str(e)[:80])

asyncio.run(main())
