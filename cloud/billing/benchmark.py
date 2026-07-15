"""040/001 — cost benchmark runner.

Drives a designated test agent through the versioned playbook exactly the way
a user would (trusted-proxy HTTP to the agent's own API), then attributes
every billable event and rated charge in each step's time window to that
playbook item. The full ordered trigger log is persisted per step; anything
that fired during the run outside every step window lands in a synthetic
'__background__' step so nothing goes unrecorded.

Guard: the runner refuses agents not flagged as benchmark targets
(`agents.config_overrides["benchmark"]["target"] == true`) — a run pollutes
the target's conversations and spends its wallet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import worker
from cloud.billing.models import (
    BenchmarkRun,
    BenchmarkStep,
    BenchmarkStepEvent,
    BillableEvent,
    RatedCharge,
)
from cloud.billing.benchmark_playbook import (
    BY_KEY,
    DEFAULT_KEYS,
    PLAYBOOK_VERSION,
    PlaybookItem,
)
from cloud.db.models import Agent

log = logging.getLogger("billing.benchmark")

BENCHMARK_JOB = "cost_benchmark"
BACKGROUND_KEY = "__background__"
SETTLE_SECONDS = 4.0          # let async rating land before closing a window
MESSAGE_TIMEOUT = 240.0


class BenchmarkError(Exception):
    pass


def is_benchmark_target(agent: Agent) -> bool:
    return bool(((agent.config_overrides or {}).get("benchmark") or {}).get("target"))


# ── Agent driver ──────────────────────────────────────────────────────────────

class HttpAgentDriver:
    """Talks to the Luna agent the way the cloud proxy does: direct HTTP to
    its internal URL with the derived per-agent trusted-proxy secret."""

    def __init__(self, agent: Agent, user_email: str):
        from cloud.runtime.proxy_secret import derive_proxy_secret

        if not agent.internal_url:
            raise BenchmarkError("agent has no internal_url — is it provisioned?")
        root = os.environ.get("CLOUD_TRUSTED_PROXY_SECRET", "dev-proxy-secret")
        self._base = agent.internal_url.rstrip("/")
        self._headers = {
            "x-luna-user": user_email,
            "x-luna-proxy-secret": derive_proxy_secret(root, str(agent.id)),
        }
        if agent.runtime_ref:
            self._headers["fly-force-instance-id"] = agent.runtime_ref
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=MESSAGE_TIMEOUT))
        self._token: str | None = None

    async def login(self) -> None:
        r = await self._client.post(f"{self._base}/api/auth/proxy-login", headers=self._headers)
        r.raise_for_status()
        self._token = r.json()["access_token"]
        self._headers["authorization"] = f"Bearer {self._token}"

    async def create_conversation(self, title: str) -> str:
        r = await self._client.post(
            f"{self._base}/api/conversations", headers=self._headers, json={"title": title}
        )
        r.raise_for_status()
        return r.json()["id"]

    async def send_message(self, conversation_id: str, text: str) -> dict:
        """POST a message and consume the SSE reply. Returns the done payload
        (reply text is discarded — never persisted)."""
        done: dict = {}
        async with self._client.stream(
            "POST",
            f"{self._base}/api/conversations/{conversation_id}/messages",
            headers=self._headers,
            json={"content": text},
        ) as resp:
            resp.raise_for_status()
            event = ""
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event == "done":
                    try:
                        done = json.loads(line.split(":", 1)[1].strip())
                    except json.JSONDecodeError:
                        done = {}
        return done

    async def api_reads(self) -> None:
        """Scripted read-only API traffic (the api.direct item)."""
        r = await self._client.get(f"{self._base}/api/conversations", headers=self._headers)
        r.raise_for_status()
        for conv in r.json()[:3]:
            m = await self._client.get(
                f"{self._base}/api/conversations/{conv['id']}/messages", headers=self._headers
            )
            m.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()


# ── Attribution ───────────────────────────────────────────────────────────────

def _q(quantities: dict | None, *keys: str) -> int:
    q = quantities or {}
    return sum(int(q.get(k) or 0) for k in keys)


async def _collect_window(
    session: AsyncSession,
    run: BenchmarkRun,
    step: BenchmarkStep,
    t0: datetime,
    t1: datetime,
    claimed: set[uuid.UUID],
    claimed_calls: set[str],
) -> None:
    """Attribute every unclaimed billable event in [t0, t1) to this step and
    write its trigger-log rows and aggregates."""
    events = (
        (
            await session.execute(
                select(BillableEvent)
                .where(
                    BillableEvent.agent_id == run.agent_id,
                    BillableEvent.event_at >= t0,
                    BillableEvent.event_at < t1,
                )
                .order_by(BillableEvent.event_at.asc(), BillableEvent.attempt_number.asc())
            )
        )
        .scalars()
        .all()
    )
    events = [e for e in events if e.id not in claimed]
    claimed.update(e.id for e in events)

    call_ids = {e.call_id for e in events}
    charges: dict[str, RatedCharge] = {}
    if call_ids:
        for rc in (
            (
                await session.execute(
                    select(RatedCharge).where(RatedCharge.logical_call_id.in_(call_ids))
                )
            )
            .scalars()
            .all()
        ):
            charges[rc.logical_call_id] = rc

    # The call's credits sit on its final attempt row (no double counting).
    # Events are ordered by (event_at, attempt) so the last write wins.
    final_attempt: dict[str, uuid.UUID] = {}
    for e in events:
        final_attempt[e.call_id] = e.id

    per_model: dict[str, dict[str, int]] = {}
    for e in events:
        rc = charges.get(e.call_id)
        credits = rc.credits if (rc and final_attempt.get(e.call_id) == e.id) else 0
        session.add(
            BenchmarkStepEvent(
                run_id=run.id,
                step_id=step.id,
                billable_event_id=e.id,
                ts=e.event_at,
                call_id=e.call_id,
                service=e.service,
                sku=e.sku,
                provider=e.provider,
                model=e.model,
                attempt_number=e.attempt_number,
                quantities=e.quantity_json,
                vendor_cost_micro_usd=e.vendor_cost_micro_usd,
                credits=credits,
                cost_source=e.cost_source,
            )
        )
        m = per_model.setdefault(
            e.model or e.service,
            {"requests": 0, "input_tokens": 0, "output_tokens": 0,
             "cache_read_tokens": 0, "cache_write_tokens": 0, "vendor_cost_micro_usd": 0},
        )
        m["requests"] += 1
        m["input_tokens"] += _q(e.quantity_json, "input_tokens")
        m["output_tokens"] += _q(e.quantity_json, "output_tokens")
        m["cache_read_tokens"] += _q(e.quantity_json, "cache_read_input_tokens", "cached_input_tokens")
        m["cache_write_tokens"] += _q(e.quantity_json, "cache_creation_input_tokens")
        m["vendor_cost_micro_usd"] += e.vendor_cost_micro_usd

    step.llm_requests = len(events)
    step.input_tokens = sum(m["input_tokens"] for m in per_model.values())
    step.output_tokens = sum(m["output_tokens"] for m in per_model.values())
    step.cache_read_tokens = sum(m["cache_read_tokens"] for m in per_model.values())
    step.cache_write_tokens = sum(m["cache_write_tokens"] for m in per_model.values())
    step.vendor_cost_micro_usd = sum(e.vendor_cost_micro_usd for e in events)
    # A call whose attempts straddle two windows must charge only once.
    fresh_charges = [rc for cid, rc in charges.items() if cid not in claimed_calls]
    claimed_calls.update(charges.keys())
    step.credits = sum(rc.credits for rc in fresh_charges)
    step.margin_micro_usd = sum(rc.margin_micro_usd for rc in fresh_charges)
    step.per_model = per_model or None
    await session.flush()


# ── Execution ─────────────────────────────────────────────────────────────────

async def _run_item(driver, item: PlaybookItem, *, sleeper) -> None:
    if item.kind == "chat":
        conv = await driver.create_conversation(f"benchmark:{item.key}")
        await driver.send_message(conv, item.prompts[0])
    elif item.kind == "chat_multi":
        conv = await driver.create_conversation(f"benchmark:{item.key}")
        for prompt in item.prompts:
            await driver.send_message(conv, prompt)
    elif item.kind == "api":
        await driver.api_reads()
    elif item.kind == "window":
        await sleeper(item.window_seconds)
    else:  # pragma: no cover — catalog is validated at start
        raise BenchmarkError(f"unknown kind {item.kind!r}")


async def execute_run(
    session: AsyncSession,
    run: BenchmarkRun,
    driver,
    *,
    settle_seconds: float = SETTLE_SECONDS,
    sleeper=asyncio.sleep,
    now=lambda: datetime.now(timezone.utc),
    on_step_done=None,
) -> dict:
    """Execute all items × repetitions on an already-'running' run row.
    Commits after every step so progress and partial results are visible
    (and survive an abort)."""
    items = [BY_KEY[k] for k in run.item_keys if k in BY_KEY]
    unknown = [k for k in run.item_keys if k not in BY_KEY]
    if unknown:
        raise BenchmarkError(f"unknown playbook items: {unknown}")

    claimed: set[uuid.UUID] = set()
    claimed_calls: set[str] = set()
    run.started_at = run.started_at or now()
    seq = 0
    total_steps = sum(
        (1 if i.kind == "window" else run.repetitions) for i in items
    ) + 1  # + background
    failed_steps = 0

    await driver.login()

    for item in items:
        reps = 1 if item.kind == "window" else run.repetitions
        for rep in range(1, reps + 1):
            # Abort is set from another transaction; read committed sees it.
            await session.refresh(run, attribute_names=["state"])
            if run.state == "aborted":
                run.finished_at = now()
                await session.commit()
                return {"state": "aborted", "steps_done": seq}

            seq += 1
            step = BenchmarkStep(
                run_id=run.id, seq=seq, item_key=item.key, repetition=rep,
                status="running", started_at=now(),
            )
            session.add(step)
            run.progress = {"item": item.key, "repetition": rep,
                            "step": seq, "total_steps": total_steps}
            await session.commit()

            t0 = now()
            wall0 = time.monotonic()
            try:
                await _run_item(driver, item, sleeper=sleeper)
                step.status = "succeeded"
            except Exception as exc:  # noqa: BLE001 — one item must not kill the run
                step.status = "failed"
                step.error = str(exc)[:2000]
                failed_steps += 1
                log.warning("benchmark item %s failed: %s", item.key, exc)
            step.latency_ms = int((time.monotonic() - wall0) * 1000)
            await sleeper(settle_seconds)
            step.finished_at = now()
            await _collect_window(session, run, step, t0, step.finished_at, claimed, claimed_calls)
            await session.commit()
            if on_step_done is not None:
                await on_step_done(step)

    # Everything that fired during the run but inside no step window.
    seq += 1
    bg = BenchmarkStep(
        run_id=run.id, seq=seq, item_key=BACKGROUND_KEY, repetition=1,
        status="running", started_at=run.started_at,
    )
    session.add(bg)
    await session.flush()
    bg.finished_at = now()
    await _collect_window(session, run, bg, run.started_at, bg.finished_at, claimed, claimed_calls)
    bg.status = "succeeded"

    steps = (
        (await session.execute(select(BenchmarkStep).where(BenchmarkStep.run_id == run.id)))
        .scalars()
        .all()
    )
    run.totals = {
        "steps": len(steps),
        "failed_steps": failed_steps,
        "credits": sum(s.credits for s in steps),
        "vendor_cost_micro_usd": sum(s.vendor_cost_micro_usd for s in steps),
        "margin_micro_usd": sum(s.margin_micro_usd for s in steps),
        "llm_requests": sum(s.llm_requests for s in steps),
        "input_tokens": sum(s.input_tokens for s in steps),
        "output_tokens": sum(s.output_tokens for s in steps),
        "background_credits": bg.credits,
    }
    run.state = "succeeded" if failed_steps == 0 else "failed"
    run.error = None if failed_steps == 0 else f"{failed_steps} step(s) failed"
    run.finished_at = now()
    await session.commit()
    return {"state": run.state, **run.totals}


# ── Start / job plumbing ──────────────────────────────────────────────────────

async def start_run(
    session: AsyncSession,
    *,
    agent: Agent,
    created_by: uuid.UUID | None,
    item_keys: list[str] | None = None,
    repetitions: int = 3,
) -> BenchmarkRun:
    """Create the run row + durable job. Refuses non-flagged agents."""
    if not is_benchmark_target(agent):
        raise BenchmarkError(
            "agent is not flagged as a benchmark target "
            "(config_overrides.benchmark.target)"
        )
    keys = list(item_keys or DEFAULT_KEYS)
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown:
        raise BenchmarkError(f"unknown playbook items: {unknown}")
    if not 1 <= repetitions <= 10:
        raise BenchmarkError("repetitions must be 1..10")
    run = BenchmarkRun(
        created_by=created_by,
        agent_id=agent.id,
        account_id=agent.account_id,
        image_version=getattr(agent, "image_version", None),
        playbook_version=PLAYBOOK_VERSION,
        item_keys=keys,
        repetitions=repetitions,
        state="pending",
    )
    session.add(run)
    await session.flush()
    await worker.enqueue(
        session,
        job_type=BENCHMARK_JOB,
        payload={"run_id": str(run.id)},
        dedupe_key=f"benchmark:{run.id}",
        max_attempts=1,  # a benchmark is not retryable money movement
    )
    return run


async def _handle_benchmark(session: AsyncSession, job) -> dict:
    from cloud.db.models import User

    run = await session.get(BenchmarkRun, uuid.UUID(job.payload["run_id"]))
    if run is None:
        raise BenchmarkError("benchmark run row not found")
    if run.state in ("succeeded", "failed", "aborted"):
        return {"state": run.state}
    agent = await session.get(Agent, run.agent_id)
    if agent is None or not is_benchmark_target(agent):
        run.state = "failed"
        run.error = "agent missing or no longer flagged as benchmark target"
        await session.flush()
        return {"state": "failed", "error": run.error}

    email = "benchmark@luna.local"
    if run.created_by:
        creator = await session.get(User, run.created_by)
        if creator is not None:
            email = creator.email

    run.state = "running"
    await session.commit()

    driver = HttpAgentDriver(agent, email)
    job_id, worker_id = job.id, job.leased_by

    async def _extend_lease(step) -> None:
        await worker.heartbeat(session, job_id, worker_id=worker_id)

    try:
        return await execute_run(session, run, driver, on_step_done=_extend_lease)
    except Exception as exc:
        await session.rollback()
        fresh = await session.get(BenchmarkRun, run.id)
        if fresh is not None and fresh.state not in ("succeeded", "aborted"):
            fresh.state = "failed"
            fresh.error = str(exc)[:2000]
            fresh.finished_at = datetime.now(timezone.utc)
            await session.commit()
        raise
    finally:
        await driver.close()


worker.register_handler(BENCHMARK_JOB, _handle_benchmark)
