"""Plan 072 — image env defaults reach new AND existing machines.

- `effective_env_overrides`: admin-stored `image_defaults.env` overlaid by the
  image's own `image_config.env`, stringified.
- `_provision_core` puts that block on the spec the runtime receives (before,
  stored default env never reached a new machine — only the image's raw env).
- `_agent_image_config` merges `env` one level deep, so the backfill pushes the
  same block a fresh machine would get.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from cloud.provisioning.image_defaults import effective_env_overrides


def test_effective_env_overrides_merge_and_stringify():
    defaults = {"env": {"LUNA_INLINE_CODE_RUN_VENV_DIR": "/workspace/.code-run-venvs", "LUNA_X": 1}}
    image = {"env": {"LUNA_X": "img", "LUNA_Y": True}}
    assert effective_env_overrides(defaults, image) == {
        "LUNA_INLINE_CODE_RUN_VENV_DIR": "/workspace/.code-run-venvs",
        "LUNA_X": "img",
        "LUNA_Y": "True",
    }
    assert effective_env_overrides({}, {}) == {}
    assert effective_env_overrides(None, {"env": None}) == {}
    assert effective_env_overrides({"env": {"A": None}}, {}) == {}


class _FakeTenantDb:
    role = "role_x"
    password = "pw"  # noqa: S105 — test fixture
    db_name = "tenant_x"


class _FakeHandle:
    runtime_kind = "fly-machine"
    runtime_ref = "machine-xyz"
    internal_url = "https://luna-agents.fly.dev"
    extra: dict = {}


@pytest.mark.asyncio
async def test_provision_core_applies_stored_default_env(db_engine, account, sample_agent):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import cloud.provisioning.workflow as wf

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    seen: dict = {}

    @asynccontextmanager
    async def _sess():
        async with factory() as s:
            yield s

    async def _fake_provision_db(admin_url, slug):
        return _FakeTenantDb()

    class _FakeRuntime:
        async def provision(self, spec):
            seen["spec"] = spec
            return _FakeHandle()

    async def _fake_catalog(db):
        return []

    async def _fake_defaults(db):
        return {"env": {"LUNA_INLINE_CODE_RUN_VENV_DIR": "/workspace/.code-run-venvs",
                        "LUNA_FROM_DEFAULT": "d"}}

    patches = (
        patch.object(wf, "get_db_session", _sess),
        patch.object(wf, "provision_tenant_database", _fake_provision_db),
        patch.object(wf, "_get_runtime", lambda: _FakeRuntime()),
        patch.object(wf, "system_catalog", _fake_catalog),
        patch.object(wf, "resolved_default_config", _fake_defaults),
        patch.object(wf, "resolve_default_heads",
                     lambda *a, **k: {"primary": "anthropic:x", "fast": "anthropic:y"}),
    )
    for p in patches:
        p.__enter__()
    try:
        await wf._provision_core(
            account, sample_agent, image_tag="registry/img:1", image_version="1",
            image_config={"env": {"LUNA_FROM_DEFAULT": "img-wins", "LUNA_FROM_IMAGE": "i"}},
        )
    finally:
        for p in patches:
            p.__exit__(None, None, None)

    env = seen["spec"].image_config["env"]
    assert env["LUNA_INLINE_CODE_RUN_VENV_DIR"] == "/workspace/.code-run-venvs"
    assert env["LUNA_FROM_DEFAULT"] == "img-wins"
    assert env["LUNA_FROM_IMAGE"] == "i"


@pytest.mark.asyncio
async def test_agent_image_config_merges_env_one_level(db_session, sample_agent):
    from cloud.api import gateway_env_delta as ged
    from cloud.db.models import LunaImage

    img = LunaImage(
        version="9.9.9", registry_tag="registry/img:9.9.9", build_status="built",
        image_config={"env": {"LUNA_IMG_ONLY": "1"}, "plugin_set": ["a"]},
    )
    db_session.add(img)
    sample_agent.image_version = "9.9.9"
    await db_session.commit()

    async def _fake_default(db):
        return {"env": {"LUNA_DEFAULT_ONLY": "d", "LUNA_IMG_ONLY": "default"}, "machine": {}}

    with patch("cloud.api.admin_routes._default_image_config", _fake_default):
        cfg = await ged._agent_image_config(db_session, sample_agent)

    assert cfg["env"] == {"LUNA_DEFAULT_ONLY": "d", "LUNA_IMG_ONLY": "1"}
    assert cfg["plugin_set"] == ["a"]
