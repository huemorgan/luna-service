"""Runtime provider abstraction for Luna instances."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from pydantic import BaseModel


class RuntimeStatus(str, Enum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    SLEEPING = "sleeping"
    ERROR = "error"
    DESTROYED = "destroyed"


@dataclass
class RuntimeHandle:
    runtime_kind: str
    runtime_ref: str
    internal_url: str
    extra: dict = field(default_factory=dict)


class AgentSpec(BaseModel):
    account_slug: str
    agent_slug: str
    db_schema: str
    db_url: str
    vault_key: str  # hex-encoded 32 bytes
    trusted_proxy_secret: str
    llm_keys: dict[str, str] = {}
    image_tag: str = "local-luna-luna:latest"


class LunaRuntime(Protocol):
    async def provision(self, spec: AgentSpec) -> RuntimeHandle: ...
    async def start(self, handle: RuntimeHandle) -> None: ...
    async def get_status(self, handle: RuntimeHandle) -> RuntimeStatus: ...
    async def stop(self, handle: RuntimeHandle) -> None: ...
    async def destroy(self, handle: RuntimeHandle) -> None: ...
