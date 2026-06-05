"""Docker-based local runtime for dev — spawns Luna containers via subprocess."""

from __future__ import annotations

import asyncio
import json
import logging

from cloud.runtime.base import AgentSpec, RuntimeHandle, RuntimeStatus

log = logging.getLogger(__name__)

NETWORK_NAME = "luna-service-net"
HEALTH_TIMEOUT = 90
HEALTH_INTERVAL = 2


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


async def _ensure_network():
    code, out, _ = await _run(["docker", "network", "ls", "--format", "{{.Name}}"])
    if NETWORK_NAME not in out.split():
        await _run(["docker", "network", "create", NETWORK_NAME])
        log.info("Created Docker network %s", NETWORK_NAME)


class DockerLocalRuntime:
    async def provision(self, spec: AgentSpec) -> RuntimeHandle:
        container_name = f"luna-{spec.account_slug}"
        internal_url = f"http://{container_name}:8000"

        await _ensure_network()

        code, out, _ = await _run(["docker", "inspect", container_name])
        if code == 0:
            info = json.loads(out)
            if info and info[0]["State"]["Running"]:
                log.info("Container %s already running", container_name)
                return RuntimeHandle("docker-local", container_name, internal_url)
            await _run(["docker", "rm", "-f", container_name])

        env_vars = {
            "LUNA_ENV": "dev",
            "LUNA_AUTH_MODE": "trusted_proxy",
            "LUNA_TRUSTED_PROXY_SECRET": spec.trusted_proxy_secret,
            "LUNA_DATABASE_URL": spec.db_url,
            "LUNA_DB_SCHEMA": spec.db_schema,
            "LUNA_VAULT_MASTER_KEY": spec.vault_key,
            "LUNA_REDIS_URL": "redis://luna-service-redis:6379/0",
            "LUNA_CORS_ORIGINS": "*",
            "LUNA_LOG_LEVEL": "INFO",
        }
        for k, v in spec.llm_keys.items():
            env_vars[k] = v

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", NETWORK_NAME,
            "--restart", "unless-stopped",
        ]
        for k, v in env_vars.items():
            cmd.extend(["-e", f"{k}={v}"])
        cmd.append(spec.image_tag)

        code, out, err = await _run(cmd)
        if code != 0:
            raise RuntimeError(f"Docker run failed: {err}")

        log.info("Started container %s", container_name)

        await self._wait_healthy(container_name, internal_url)
        return RuntimeHandle("docker-local", container_name, internal_url)

    async def _wait_healthy(self, container_name: str, url: str):
        for attempt in range(HEALTH_TIMEOUT // HEALTH_INTERVAL):
            code, out, _ = await _run([
                "docker", "exec", container_name,
                "curl", "-sf", "http://localhost:8000/api/health"
            ])
            if code == 0:
                log.info("Container %s is healthy", container_name)
                return
            await asyncio.sleep(HEALTH_INTERVAL)
        raise RuntimeError(f"Container {container_name} failed health check after {HEALTH_TIMEOUT}s")

    async def start(self, handle: RuntimeHandle) -> None:
        code, _, err = await _run(["docker", "start", handle.runtime_ref])
        if code != 0:
            raise RuntimeError(f"Docker start failed: {err}")
        log.info("Started container %s", handle.runtime_ref)

    async def get_status(self, handle: RuntimeHandle) -> RuntimeStatus:
        code, out, _ = await _run(["docker", "inspect", "-f", "{{.State.Status}}", handle.runtime_ref])
        if code != 0:
            return RuntimeStatus.DESTROYED
        status_str = out.strip()
        return {
            "running": RuntimeStatus.RUNNING,
            "exited": RuntimeStatus.ERROR,
            "paused": RuntimeStatus.SLEEPING,
            "created": RuntimeStatus.PROVISIONING,
        }.get(status_str, RuntimeStatus.ERROR)

    async def stop(self, handle: RuntimeHandle) -> None:
        await _run(["docker", "stop", handle.runtime_ref])

    async def destroy(self, handle: RuntimeHandle) -> None:
        await _run(["docker", "rm", "-f", handle.runtime_ref])
