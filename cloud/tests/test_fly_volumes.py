"""Plan 025.5 — per-agent persistent Fly volume for plugin-files.

Unit tests for the runtime volume logic, with a fake Fly Machines API client.
"""

from __future__ import annotations

import re

import pytest

from cloud.runtime.base import AgentSpec, RuntimeHandle
from cloud.runtime.fly_machines import (
    FILES_ROOT,
    SCRATCH_DIR,
    WORKSPACE_MOUNT,
    FlyMachinesRuntime,
    files_env,
    volume_name,
)


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class FakeFly:
    """Minimal stand-in for the Fly Machines httpx client."""

    def __init__(self, machines=None, volumes=None, machine_record=None):
        self.machines = machines if machines is not None else []
        self.volumes = volumes if volumes is not None else []
        self.machine_record = machine_record or {}
        self.calls: list = []
        self._vol_counter = 0

    async def get(self, path):
        self.calls.append(("GET", path))
        if path == "/machines":
            return FakeResp(200, self.machines)
        if path == "/volumes":
            return FakeResp(200, list(self.volumes))
        if path.startswith("/machines/") and "/wait" in path:
            return FakeResp(200, {})
        if path.startswith("/machines/"):
            return FakeResp(200, self.machine_record)
        return FakeResp(404, {})

    async def post(self, path, json=None):
        self.calls.append(("POST", path, json))
        if path == "/volumes":
            self._vol_counter += 1
            vol = {
                "id": f"vol_{self._vol_counter}",
                "name": json["name"],
                "region": json["region"],
                "state": "created",
            }
            self.volumes.append(vol)
            return FakeResp(201, vol)
        if path == "/machines":
            return FakeResp(201, {"id": "machine_new"})
        if path.startswith("/machines/"):
            return FakeResp(200, {"id": path.split("/")[-1]})
        return FakeResp(404, {})

    async def delete(self, path):
        self.calls.append(("DELETE", path))
        return FakeResp(200, {})


def _runtime(fake: FakeFly) -> FlyMachinesRuntime:
    rt = FlyMachinesRuntime(api_token="t", app_name="luna-agents", region="sjc")
    rt._client = fake  # inject the fake
    return rt


def _spec(slug="acct-my-luna") -> AgentSpec:
    return AgentSpec(
        account_slug="acct",
        agent_slug=slug,
        db_schema="",
        db_url="postgresql+asyncpg://u:p@h/db",
        vault_key="ab" * 32,
        trusted_proxy_secret="secret",
    )


def test_volume_name_sanitizes_slug():
    name = volume_name("acct-my-luna")
    assert name.startswith("luna_acct_my_luna_")
    assert re.fullmatch(r"[a-z0-9_]+", name)


def test_volume_name_respects_fly_30_char_limit():
    # Long slugs used to overflow Fly's 30-char limit (caused a 400 on create).
    long_slug = "vaselin-test-0-13-016-8-5-pluginsdk-9849753"
    name = volume_name(long_slug)
    assert len(name) <= 30
    assert re.fullmatch(r"[a-z0-9_]+", name)


def test_volume_name_is_deterministic_and_unique():
    assert volume_name("acct-my-luna") == volume_name("acct-my-luna")
    # Distinct slugs that share a truncated prefix must not collide (hash suffix).
    a = volume_name("vaselin-test-0-19-001-aaaaaaaaaaaaaaa")
    b = volume_name("vaselin-test-0-19-001-bbbbbbbbbbbbbbb")
    assert a != b


def test_files_env_declares_durable_fly_backend():
    env = files_env()
    assert env["LUNA_FILES_BACKEND"] == "fly"
    assert env["LUNA_FILES_ROOT"] == FILES_ROOT
    assert env["LUNA_FILES_DURABLE"] == "1"
    assert env["LUNA_SCRATCH_DIR"] == SCRATCH_DIR
    assert env["TMPDIR"] == SCRATCH_DIR


@pytest.mark.asyncio
async def test_provision_creates_and_mounts_volume():
    fake = FakeFly()
    rt = _runtime(fake)

    handle = await rt.provision(_spec())

    assert handle.extra["volume_id"] == "vol_1"
    assert handle.extra["volume_region"] == "sjc"

    post_machine = next(c for c in fake.calls if c[0] == "POST" and c[1] == "/machines")
    cfg = post_machine[2]["config"]
    assert cfg["mounts"] == [{"volume": "vol_1", "path": WORKSPACE_MOUNT}]
    assert cfg["env"]["LUNA_FILES_BACKEND"] == "fly"
    assert cfg["env"]["LUNA_FILES_ROOT"] == "/workspace/files"
    assert cfg["env"]["TMPDIR"] == SCRATCH_DIR
    # volume created in the same region as the machine
    post_vol = next(c for c in fake.calls if c[0] == "POST" and c[1] == "/volumes")
    assert post_vol[2]["region"] == "sjc"
    assert post_vol[2]["encrypted"] is True


@pytest.mark.asyncio
async def test_provision_reuses_existing_volume_by_name():
    name = volume_name("acct-my-luna")
    fake = FakeFly(volumes=[{"id": "vol_existing", "name": name, "region": "sjc", "state": "created"}])
    rt = _runtime(fake)

    handle = await rt.provision(_spec())

    assert handle.extra["volume_id"] == "vol_existing"
    # must NOT create a second volume
    assert not any(c[0] == "POST" and c[1] == "/volumes" for c in fake.calls)


@pytest.mark.asyncio
async def test_destroy_deletes_machine_and_volume():
    fake = FakeFly()
    rt = _runtime(fake)

    await rt.destroy(RuntimeHandle("fly-machine", "m1", "", extra={"volume_id": "vol_9"}))

    assert ("DELETE", "/machines/m1?force=true") in fake.calls
    assert ("DELETE", "/volumes/vol_9") in fake.calls


@pytest.mark.asyncio
async def test_destroy_resolves_volume_by_slug_when_id_missing():
    name = volume_name("acct-my-luna")
    fake = FakeFly(volumes=[{"id": "vol_found", "name": name, "region": "sjc", "state": "created"}])
    rt = _runtime(fake)

    await rt.destroy(RuntimeHandle("fly-machine", "m1", "", extra={"agent_slug": "acct-my-luna"}))

    assert ("DELETE", "/volumes/vol_found") in fake.calls


@pytest.mark.asyncio
async def test_attach_volume_skips_when_already_mounted():
    fake = FakeFly(machine_record={
        "region": "sjc",
        "config": {"env": {}, "mounts": [{"path": "/workspace", "volume": "vol_x"}]},
    })
    rt = _runtime(fake)

    res = await rt.attach_volume("m1", "acct-my-luna")

    assert res["skipped"] is True
    assert res["volume_id"] == "vol_x"
    # no config POST, no volume create
    assert not any(c[0] == "POST" and c[1] == "/machines/m1" for c in fake.calls)


@pytest.mark.asyncio
async def test_attach_volume_creates_and_mounts_preserving_env():
    fake = FakeFly(machine_record={"region": "ord", "config": {"env": {"FOO": "bar"}}})
    rt = _runtime(fake)

    res = await rt.attach_volume("m1", "acct-my-luna")

    assert res["skipped"] is False
    assert res["volume_region"] == "ord"
    post_cfg = next(c for c in fake.calls if c[0] == "POST" and c[1] == "/machines/m1")[2]["config"]
    assert post_cfg["mounts"][0]["path"] == WORKSPACE_MOUNT
    assert post_cfg["env"]["LUNA_FILES_BACKEND"] == "fly"
    assert post_cfg["env"]["FOO"] == "bar"  # existing env preserved
