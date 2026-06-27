"""Fly Machines runtime — provisions Luna instances on Fly.io."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re

import httpx

from cloud.runtime.base import AgentSpec, RuntimeHandle, RuntimeStatus

log = logging.getLogger(__name__)

HEALTH_TIMEOUT = 90
HEALTH_INTERVAL = 3

# Plan 025.5: per-agent persistent files. Each agent gets a Fly Volume mounted at
# WORKSPACE_MOUNT; plugin-files runs in `fly` backend mode against FILES_ROOT.
WORKSPACE_MOUNT = "/workspace"
FILES_ROOT = "/workspace/files"
SCRATCH_DIR = "/tmp/luna-scratch"
DEFAULT_VOLUME_GB = 1
SNAPSHOT_RETENTION_DAYS = 7


VOLUME_NAME_MAX = 30  # Fly hard limit: [a-z0-9_], at most 30 chars


def volume_name(agent_slug: str) -> str:
    """Deterministic Fly volume name for an agent.

    Fly requires lowercase alphanumeric + underscores, max 30 chars. Slugs can be
    longer than that, so we keep a readable prefix of the (sanitized) slug and
    append a short hash of the *full* slug for uniqueness. Deterministic, so
    provision/attach/destroy all resolve the same volume for a given agent.
    """
    sanitized = re.sub(r"[^a-z0-9]+", "_", agent_slug.lower()).strip("_") or "agent"
    digest = hashlib.sha256(agent_slug.encode()).hexdigest()[:6]
    # budget: "luna_" (5) + base + "_" (1) + digest (6) == 30  ->  base <= 18
    base = sanitized[: VOLUME_NAME_MAX - 5 - 1 - len(digest)].strip("_") or "agent"
    return f"luna_{base}_{digest}"


def files_env(root: str = FILES_ROOT, scratch: str = SCRATCH_DIR) -> dict[str, str]:
    """Env that tells plugin-files the mount is a durable Fly volume + pins scratch."""
    return {
        "LUNA_FILES_BACKEND": "fly",
        "LUNA_FILES_ROOT": root,
        "LUNA_FILES_DURABLE": "1",
        "LUNA_SCRATCH_DIR": scratch,
        "TMPDIR": scratch,
    }


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

    async def _ensure_volume(
        self, client: httpx.AsyncClient, name: str, region: str, size_gb: int
    ) -> dict:
        """Find an agent's volume by (name, region) or create it. Idempotent.

        Reuse-by-name is what makes recreate safe: the destroy-then-recreate path
        in provision() re-attaches the SAME disk instead of orphaning data.
        """
        resp = await client.get("/volumes")
        resp.raise_for_status()
        for v in resp.json():
            if (
                v.get("name") == name
                and v.get("region") == region
                and v.get("state") not in ("destroyed", "destroying")
            ):
                log.info("Reusing Fly volume %s (id=%s) in %s", name, v["id"], region)
                return v
        resp = await client.post(
            "/volumes",
            json={
                "name": name,
                "region": region,
                "size_gb": size_gb,
                "encrypted": True,
                "snapshot_retention": SNAPSHOT_RETENTION_DAYS,
            },
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Fly create volume failed ({resp.status_code}): {resp.text}")
        vol = resp.json()
        log.info("Created Fly volume %s (id=%s, %sGB) in %s", name, vol["id"], size_gb, region)
        await self._wait_volume_ready(client, vol["id"])
        return vol

    async def _wait_volume_ready(self, client: httpx.AsyncClient, volume_id: str, timeout: int = 20) -> None:
        """Poll a freshly-created volume until Fly reports it 'created'.

        Without this, an immediate machine-create can race ahead of Fly's volume
        propagation and fail with 'volume not found'.
        """
        import asyncio
        for _ in range(timeout):
            resp = await client.get(f"/volumes/{volume_id}")
            if resp.status_code == 200 and resp.json().get("state") == "created":
                return
            await asyncio.sleep(1)
        log.warning("Volume %s not 'created' after %ss — proceeding anyway", volume_id, timeout)

    async def _delete_volume(self, client: httpx.AsyncClient, volume_id: str) -> None:
        """Delete a volume, tolerating 'still attached' for a few seconds and 404."""
        import asyncio
        for attempt in range(5):
            resp = await client.delete(f"/volumes/{volume_id}")
            if resp.status_code in (200, 202, 204, 404):
                log.info("Deleted Fly volume %s", volume_id)
                return
            # 409/422: machine not fully gone yet — back off and retry.
            log.warning(
                "Volume delete %s returned %s (attempt %s): %s",
                volume_id, resp.status_code, attempt + 1, resp.text[:200],
            )
            await asyncio.sleep(3)
        log.error("Gave up deleting volume %s — may be orphaned, needs sweep", volume_id)

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
                log.warning("Machine %s in state '%s' — destroying before recreate", machine_name, state)
                await client.delete(f"/machines/{mid}?force=true")
                log.info("Destroyed stale machine %s (id=%s)", machine_name, mid)

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

        # Plan 018: inject the system model catalog (Luna 007.016 LUNA_MODEL_CATALOG).
        catalog = models_cfg.get("catalog")
        if catalog:
            env_vars["LUNA_MODEL_CATALOG"] = json.dumps(catalog)

        env_vars.update(env_overrides)

        region = machine_cfg.get("region", self.region)

        # Plan 025.5: ensure a per-agent persistent Fly volume, mount it at
        # /workspace, and tell plugin-files this root is durable. Volume is
        # created in the SAME region as the machine (Fly requires this).
        size_gb = machine_cfg.get("volume_gb", DEFAULT_VOLUME_GB)
        vol_name = volume_name(spec.agent_slug)
        vol = await self._ensure_volume(client, vol_name, region, size_gb)
        volume_id = vol["id"]
        env_vars.update(files_env())

        payload = {
            "name": machine_name,
            "region": region,
            "config": {
                "image": spec.image_tag if spec.image_tag != "local-luna-luna:latest" else self.image,
                "env": env_vars,
                "mounts": [{"volume": volume_id, "path": WORKSPACE_MOUNT}],
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

        import asyncio
        resp = None
        for attempt in range(4):
            resp = await client.post("/machines", json=payload)
            if resp.status_code in (200, 201):
                break
            # Fly can briefly report a just-created volume as missing — back off.
            if resp.status_code == 400 and "volume not found" in resp.text.lower():
                log.warning("Machine create saw 'volume not found' (attempt %s) — retrying", attempt + 1)
                await asyncio.sleep(3)
                continue
            raise RuntimeError(f"Fly create machine failed ({resp.status_code}): {resp.text}")
        if not resp or resp.status_code not in (200, 201):
            raise RuntimeError(f"Fly create machine failed ({resp.status_code if resp else '—'}): "
                               f"{resp.text if resp else 'no response'}")

        data = resp.json()
        machine_id = data["id"]
        log.info("Created Fly machine %s (id=%s) in %s", machine_name, machine_id, self.region)

        await self._wait_healthy(machine_id)

        internal_url = f"https://{self.app_name}.fly.dev"
        return RuntimeHandle(
            "fly-machine",
            machine_id,
            internal_url,
            extra={
                "volume_id": volume_id,
                "volume_region": region,
                "volume_size_gb": size_gb,
            },
        )

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

        # Plan 025.5: remove the agent's persistent volume so we don't pay for
        # orphans. Prefer the stored volume_id; fall back to name lookup.
        extra = handle.extra or {}
        volume_id = extra.get("volume_id")
        if not volume_id and extra.get("agent_slug"):
            try:
                resp = await client.get("/volumes")
                if resp.status_code == 200:
                    target = volume_name(extra["agent_slug"])
                    for v in resp.json():
                        if v.get("name") == target:
                            volume_id = v["id"]
                            break
            except Exception as e:
                log.warning("Volume lookup failed during destroy: %s", e)
        if volume_id:
            try:
                await self._delete_volume(client, volume_id)
            except Exception as e:
                log.warning("Failed to delete volume %s during destroy: %s", volume_id, e)

    async def attach_volume(
        self,
        machine_id: str,
        agent_slug: str,
        region: str | None = None,
        size_gb: int = DEFAULT_VOLUME_GB,
    ) -> dict:
        """Backfill: attach a persistent volume + files env to an existing machine.

        Idempotent — if the machine already mounts /workspace, returns skipped.
        Recreates the machine with the new config (Fly behavior); the old
        ephemeral ~/.luna/files was never durable, so nothing real is lost.
        """
        client = self._get_client()
        resp = await client.get(f"/machines/{machine_id}")
        if resp.status_code == 404:
            log.info("Machine %s not found — skipping volume attach", machine_id)
            return {"skipped": True, "reason": "machine_not_found"}
        resp.raise_for_status()
        machine = resp.json()

        # A destroyed (or otherwise non-updatable) machine can't take a config
        # update — bail BEFORE creating a volume so we don't orphan one. Stale
        # DB records pointing at long-gone machines are common after churn.
        state = machine.get("state")
        if state not in ("started", "stopped"):
            log.info("Machine %s is %s — skipping volume attach", machine_id, state)
            return {"skipped": True, "reason": f"machine_{state}"}

        config = machine.get("config", {})
        region = region or machine.get("region") or self.region

        mounts = config.get("mounts") or []
        if any(m.get("path") == WORKSPACE_MOUNT for m in mounts):
            existing = mounts[0].get("volume")
            log.info("Machine %s already has a /workspace mount (vol=%s)", machine_id, existing)
            return {
                "volume_id": existing,
                "volume_region": region,
                "volume_size_gb": size_gb,
                "skipped": True,
            }

        vol = await self._ensure_volume(client, volume_name(agent_slug), region, size_gb)
        config["mounts"] = [{"volume": vol["id"], "path": WORKSPACE_MOUNT}]
        env = dict(config.get("env", {}))
        env.update(files_env())
        config["env"] = env

        resp = await client.post(f"/machines/{machine_id}", json={"config": config})
        resp.raise_for_status()
        await self._wait_healthy(machine_id)
        log.info("Attached volume %s to machine %s at /workspace", vol["id"], machine_id)
        return {
            "volume_id": vol["id"],
            "volume_region": region,
            "volume_size_gb": size_gb,
            "skipped": False,
        }

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

    async def update_machine_env(self, machine_id: str, env_updates: dict[str, str],
                                 remove_keys: list[str] | None = None) -> dict:
        """Merge env vars into a machine's config in place (keeps volume + id).

        Updating config triggers Fly to recreate the machine with the new env
        and restart it. Used by the 014 fleet migration to repoint each agent
        at its isolated DB and rotate its trusted-proxy secret.
        """
        client = self._get_client()
        resp = await client.get(f"/machines/{machine_id}")
        resp.raise_for_status()
        machine = resp.json()
        config = machine.get("config", {})
        env = dict(config.get("env", {}))
        env.update(env_updates)
        for k in (remove_keys or []):
            env.pop(k, None)
        config["env"] = env
        resp = await client.post(f"/machines/{machine_id}", json={"config": config})
        resp.raise_for_status()
        await self._wait_healthy(machine_id)
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
