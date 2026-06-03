"""Quick smoke test for Fly Machines API access."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from cloud.runtime.fly_machines import FlyMachinesRuntime


async def main():
    runtime = FlyMachinesRuntime()
    client = runtime._get_client()

    print(f"App: {runtime.app_name}")
    print(f"Region: {runtime.region}")
    print(f"Image: {runtime.image}")

    resp = await client.get("/machines")
    resp.raise_for_status()
    machines = resp.json()
    print(f"Machines: {len(machines)}")
    for m in machines:
        print(f"  - {m['name']} ({m['id']}): {m.get('state', '?')}")

    await client.aclose()
    print("Fly API access OK")


asyncio.run(main())
