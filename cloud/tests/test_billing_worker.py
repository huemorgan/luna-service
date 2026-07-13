"""039/001 — durable billing worker: leases, retries, dead-letter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cloud.billing import worker
from cloud.billing.models import BillingJob
from cloud.billing.worker import (
    BASE_BACKOFF,
    MAX_BACKOFF,
    backoff_for_attempt,
    claim_jobs,
    complete_job,
    enqueue,
    fail_job,
    heartbeat,
    register_handler,
    run_claimed_job,
)

NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)

asyncio_test = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_handlers():
    saved = dict(worker._handlers)
    worker._handlers.clear()
    yield
    worker._handlers.clear()
    worker._handlers.update(saved)


def test_backoff_bounded():
    assert backoff_for_attempt(1) == BASE_BACKOFF
    assert backoff_for_attempt(2) == BASE_BACKOFF * 2
    assert backoff_for_attempt(100) == MAX_BACKOFF


@asyncio_test
async def test_enqueue_dedupe(db_session):
    j1 = await enqueue(db_session, job_type="t", payload={"n": 1}, dedupe_key="k1")
    j2 = await enqueue(db_session, job_type="t", payload={"n": 2}, dedupe_key="k1")
    assert j1.id == j2.id
    assert j1.payload == {"n": 1}


@asyncio_test
async def test_claim_and_complete(db_session):
    await enqueue(db_session, job_type="t", payload={}, run_at=NOW)
    jobs = await claim_jobs(db_session, worker_id="w1", now=NOW)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.status == "running" and job.leased_by == "w1" and job.attempts == 1
    # Claimed jobs are invisible to other workers while leased.
    assert await claim_jobs(db_session, worker_id="w2", now=NOW) == []
    await complete_job(db_session, job, {"ok": True})
    assert job.status == "succeeded"
    # Succeeded jobs never reclaim.
    assert await claim_jobs(db_session, worker_id="w2", now=NOW + timedelta(hours=1)) == []


@asyncio_test
async def test_future_jobs_not_claimed(db_session):
    await enqueue(db_session, job_type="t", payload={}, run_at=NOW + timedelta(minutes=5))
    assert await claim_jobs(db_session, worker_id="w1", now=NOW) == []
    assert len(await claim_jobs(db_session, worker_id="w1", now=NOW + timedelta(minutes=5))) == 1


@asyncio_test
async def test_expired_lease_reclaimed_exactly_once(db_session):
    await enqueue(db_session, job_type="t", payload={}, run_at=NOW)
    [job] = await claim_jobs(db_session, worker_id="w1", lease=timedelta(minutes=5), now=NOW)
    # Crash simulation: w1 never completes. After lease expiry w2 reclaims.
    later = NOW + timedelta(minutes=6)
    [reclaimed] = await claim_jobs(db_session, worker_id="w2", now=later)
    assert reclaimed.id == job.id
    assert reclaimed.leased_by == "w2" and reclaimed.attempts == 2
    # w1's heartbeat now fails — it no longer owns the job.
    assert await heartbeat(db_session, job.id, worker_id="w1", now=later) is False
    assert await heartbeat(db_session, job.id, worker_id="w2", now=later) is True


@asyncio_test
async def test_handler_success_and_result(db_session):
    async def handler(session, job):
        return {"processed": job.payload["n"]}
    register_handler("ok_job", handler)
    await enqueue(db_session, job_type="ok_job", payload={"n": 7}, run_at=NOW)
    [job] = await claim_jobs(db_session, worker_id="w1", now=NOW)
    assert await run_claimed_job(db_session, job) is True
    assert job.status == "succeeded" and job.result == {"processed": 7}


@asyncio_test
async def test_handler_failure_retries_then_dead(db_session):
    async def handler(session, job):
        raise RuntimeError("boom")
    register_handler("bad_job", handler)
    await enqueue(db_session, job_type="bad_job", payload={}, run_at=NOW, max_attempts=2)
    await db_session.commit()

    [job] = await claim_jobs(db_session, worker_id="w1", now=NOW)
    await db_session.commit()
    assert await run_claimed_job(db_session, job) is False
    await db_session.commit()
    job = await db_session.get(BillingJob, job.id)
    assert job.status == "pending"
    assert job.next_attempt_at is not None and "boom" in job.last_error

    # fail_job stamps next_attempt_at from the real clock; claim far in the future.
    retry_at = datetime.now(timezone.utc) + timedelta(days=1)
    [job] = await claim_jobs(db_session, worker_id="w1", now=retry_at)
    await db_session.commit()
    assert await run_claimed_job(db_session, job) is False
    await db_session.commit()
    job = await db_session.get(BillingJob, job.id)
    assert job.status == "dead"  # attempts (2) >= max_attempts (2)
    # Dead jobs are never claimed again.
    assert await claim_jobs(db_session, worker_id="w1", now=retry_at + timedelta(days=1)) == []


@asyncio_test
async def test_unregistered_job_type_fails_not_crashes(db_session):
    await enqueue(db_session, job_type="ghost", payload={}, run_at=NOW, max_attempts=1)
    [job] = await claim_jobs(db_session, worker_id="w1", now=NOW)
    assert await run_claimed_job(db_session, job) is False
    assert job.status == "dead"
    assert "no handler" in job.last_error
