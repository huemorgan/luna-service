"""Usage metering: best-effort token extraction + usage_events writes."""

from __future__ import annotations

import re
import uuid

from cloud.db.models import UsageEvent
from cloud.db import session as db_session

# Anthropic: "input_tokens": N (message_start), "output_tokens": N (message_delta).
# OpenAI: "prompt_tokens": N / "completion_tokens": N (final usage chunk).
_INPUT_RE = re.compile(rb'"(?:input_tokens|prompt_tokens)"\s*:\s*(\d+)')
_OUTPUT_RE = re.compile(rb'"(?:output_tokens|completion_tokens)"\s*:\s*(\d+)')

# Only scan response bodies that can plausibly contain usage JSON.
_SCANNABLE_TYPES = ("application/json", "text/event-stream")


class UsageScanner:
    """Accumulates token counts while a response streams through the proxy.

    Best-effort: LLM responses report usage in their body; non-LLM services
    simply produce no matches and we record request_count only.
    """

    def __init__(self, content_type: str) -> None:
        self._scan = any(t in content_type for t in _SCANNABLE_TYPES)
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self._tail = b""

    def feed(self, chunk: bytes) -> None:
        if not self._scan:
            return
        buf = self._tail + chunk
        for m in _INPUT_RE.finditer(buf):
            val = int(m.group(1))
            self.input_tokens = max(self.input_tokens or 0, val)
        for m in _OUTPUT_RE.finditer(buf):
            val = int(m.group(1))
            self.output_tokens = max(self.output_tokens or 0, val)
        # Keep a tail so a pattern split across chunk boundaries still matches.
        self._tail = buf[-256:]


async def record_usage(
    *,
    agent_id: uuid.UUID | None,
    service_slug: str,
    billable: bool,
    key_id: uuid.UUID | None,
    status_code: int | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """Write one usage event in its own session (called from stream finalizers)."""
    async with db_session.get_session() as db:
        db.add(UsageEvent(
            agent_id=agent_id,
            service_slug=service_slug,
            billable=billable,
            key_id=key_id,
            status_code=status_code,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ))
        await db.commit()
