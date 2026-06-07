"""Fly Machines runtime — provisions Luna instances on Fly.io."""

from __future__ import annotations

import logging
import os

import httpx

from cloud.runtime.base import AgentSpec, RuntimeHandle, RuntimeStatus

log = logging.getLogger(__name__)

HEALTH_TIMEOUT = 90
HEALTH_INTERVAL = 3


class FlyMachinesRuntime:
    def __init__(
        self,
        api_token: str | None = None,
        app_name: str | None = None,
        region: str | None = None,
        image: str | None = None,
    ):
        self.api_token = api_token or os.environ["FLY_API_TOKEN"]
        self.app_name = app_name or os.environ.get("FLY_APP", "luna-agents")
        self.region = region or os.environ.get("FLY_REGION", "sjc")
        self.image = image or os.environ.get(
            "FLY_LUNA_IMAGE",
            f"registry.fly.io/{self.app_name}:latest",
        )
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"https://api.machines.dev/v1/apps/{self.app_name}",
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=httpx.Timeout(60, connect=10),
            )
        return self._client

    async def provision(self, spec: AgentSpec) -> RuntimeHandle:
        client = self._get_client()
        machine_name = f"luna-{spec.agent_slug}"

        existing = await client.get("/machines")
        existing.raise_for_status()
        for m in existing.json():
            if m.get("name") == machine_name:
                mid = m["id"]
                state = m.get("state", "")
                url = f"https://{self.app_name}.fly.dev"
                if state in ("started", "running"):
                    log.info("Machine %s already running (id=%s)", machine_name, mid)
                    return RuntimeHandle("fly-machine", mid, url)
                if state in ("stopped", "suspended"):
                    await client.post(f"/machines/{mid}/start")
                    log.info("Restarted machine %s (id=%s)", machine_name, mid)
                    await self._wait_healthy(mid)
                    return RuntimeHandle("fly-machine", mid, url)

        ic = spec.image_config
        machine_cfg = ic.get("machine", {})
        models_cfg = ic.get("models", {})
        plugins_cfg = ic.get("plugins", {})
        env_overrides = ic.get("env", {})

        env_vars = {
            "LUNA_ENV": "production",
            "LUNA_AUTH_MODE": "trusted_proxy",
            "LUNA_TRUSTED_PROXY_SECRET": spec.trusted_proxy_secret,
            "LUNA_DATABASE_URL": spec.db_url,
            "LUNA_DB_SCHEMA": spec.db_schema,
            "LUNA_VAULT_MASTER_KEY": spec.vault_key,
            "LUNA_REDIS_URL": "",
            "LUNA_CORS_ORIGINS": "*",
            "LUNA_LOG_LEVEL": "INFO",
        }
        for k, v in spec.llm_keys.items():
            env_vars[k] = v

        disabled = [k for k, v in plugins_cfg.items() if v is False]
        if disabled:
            env_vars["LUNA_DISABLED_PLUGINS"] = ",".join(disabled)

        primary = models_cfg.get("primary", {})
        fast = models_cfg.get("fast", {})
        if primary.get("model"):
            env_vars["LUNA_PRIMARY_MODEL"] = f"{primary.get('provider', 'anthropic')}:{primary['model']}"
        if fast.get("model"):
            env_vars["LUNA_FAST_MODEL"] = f"{fast.get('provider', 'anthropic')}:{fast['model']}"

        env_vars.update(env_overrides)

        region = machine_cfg.get("region", self.region)

        payload = {
            "name": machine_name,
            "region": region,
            "config": {
                "image": spec.image_tag if spec.image_tag != "local-luna-luna:latest" else self.image,
                "env": env_vars,
                "restart": {"policy": "always"},
                "auto_destroy": False,
                "guest": {
                    "cpu_kind": machine_cfg.get("cpu_kind", "shared"),
                    "cpus": machine_cfg.get("cpus", 1),
                    "memory_mb": machine_cfg.get("memory_mb", 1024),
                },
                "services": [
                    {
                        "ports": [
                            {"port": 443, "handlers": ["tls", "http"]},
                            {"port": 80, "handlers": ["http"]},
                        ],
                        "protocol": "tcp",
                        "internal_port": 8000,
                        "autostop": "off",
                        "autostart": True,
                        "min_machines_running": 1,
                    }
                ],
                "checks": {
                    "httpget": {
                        "type": "http",
                        "port": 8000,
                        "method": "GET",
                        "path": "/api/health",
                        "interval": "15s",
                        "timeout": "5s",
                    }
                },
            },
        }

        resp = await client.post("/machines", json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Fly create machine failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        machine_id = data["id"]
        log.info("Created Fly machine %s (id=%s) in %s", machine_name, machine_id, self.region)

        await self._wait_healthy(machine_id)

        internal_url = f"https://{self.app_name}.fly.dev"
        return RuntimeHandle("fly-machine", machine_id, internal_url)

    async def _wait_healthy(self, machine_id: str):
        import asyncio
        client = self._get_client()
        for attempt in range(HEALTH_TIMEOUT // HEALTH_INTERVAL):
            resp = await client.get(f"/machines/{machine_id}/wait?state=started&timeout=10")
            if resp.status_code == 200:
                log.info("Machine %s is started", machine_id)
                return
            await asyncio.sleep(HEALTH_INTERVAL)
        raise RuntimeError(f"Machine {machine_id} failed to start after {HEALTH_TIMEOUT}s")

    async def start(self, handle: RuntimeHandle) -> None:
        client = self._get_client()
        resp = await client.get(f"/machines/{handle.runtime_ref}")
        resp.raise_for_status()
        state = resp.json().get("state", "")
        if state in ("started", "running"):
            return
        await client.post(f"/machines/{handle.runtime_ref}/start")
        log.info("Starting machine %s", handle.runtime_ref)
        await self._wait_healthy(handle.runtime_ref)

    async def get_status(self, handle: RuntimeHandle) -> RuntimeStatus:
        client = self._get_client()
        resp = await client.get(f"/machines/{handle.runtime_ref}")
        if resp.status_code == 404:
            return RuntimeStatus.DESTROYED
        resp.raise_for_status()
        state = resp.json().get("state", "")
        return {
            "started": RuntimeStatus.RUNNING,
            "running": RuntimeStatus.RUNNING,
            "stopped": RuntimeStatus.SLEEPING,
            "suspended": RuntimeStatus.SLEEPING,
            "created": RuntimeStatus.PROVISIONING,
            "destroying": RuntimeStatus.DESTROYED,
            "destroyed": RuntimeStatus.DESTROYED,
        }.get(state, RuntimeStatus.ERROR)

    async def stop(self, handle: RuntimeHandle) -> None:
        client = self._get_client()
        await client.post(f"/machines/{handle.runtime_ref}/stop")

    async def destroy(self, handle: RuntimeHandle) -> None:
        client = self._get_client()
        await client.delete(f"/machines/{handle.runtime_ref}?force=true")

    async def list_machines(self) -> list[dict]:
        client = self._get_client()
        resp = await client.get("/machines")
        resp.raise_for_status()
        return resp.json()

    async def update_machine_image(self, machine_id: str, new_image: str) -> dict:
        client = self._get_client()
        resp = await client.get(f"/machines/{machine_id}")
        resp.raise_for_status()
        machine = resp.json()
        config = machine.get("config", {})
        config["image"] = new_image
        resp = await client.post(f"/machines/{machine_id}", json={"config": config})
        resp.raise_for_status()
        return resp.json()

    async def warm_image_cache(self, image_tag: str, region: str | None = None) -> None:
        """Pull an image into Fly's regional cache by creating and destroying a throwaway machine."""
        import asyncio
        client = self._get_client()
        target_region = region or self.region
        payload = {
            "name": f"cache-warm-{target_region}-{id(self)}",
            "region": target_region,
            "config": {
                "image": image_tag,
                "auto_destroy": True,
                "restart": {"policy": "no"},
                "guest": {"cpu_kind": "shared", "cpus": 1, "memory_mb": 256},
            },
        }
        resp = await client.post("/machines", json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Cache warm failed ({resp.status_code}): {resp.text}")

        machine_id = resp.json()["id"]
        log.info("Cache-warming %s in %s (machine %s)", image_tag, target_region, machine_id)

        try:
            for _ in range(HEALTH_TIMEOUT // HEALTH_INTERVAL):
                resp = await client.get(f"/machines/{machine_id}/wait?state=started&timeout=10")
                if resp.status_code == 200:
                    break
                await asyncio.sleep(HEALTH_INTERVAL)
        finally:
            await client.delete(f"/machines/{machine_id}?force=true")
            log.info("Cache-warm machine %s destroyed", machine_id)

    async def describe(self, machine_id: str) -> dict | None:
        """Return the full Fly Machine record, or None if it no longer exists.

        Used by the agent detail endpoint to surface live compute info
        (region, image, guest size, state, events) without caching them
        in our DB long-term. Caller is responsible for short-TTL caching.
        """
        client = self._get_client()
        try:
            resp = await client.get(f"/machines/{machine_id}")
        except httpx.HTTPError as exc:
            log.warning("Fly describe failed for %s: %s", machine_id, exc)
            return None
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            log.warning("Fly describe %s returned %s", machine_id, resp.status_code)
            return None
        return resp.json()
