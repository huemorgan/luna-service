"""Cost benchmark: playbook coverage, runner attribution, profile math (040)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cloud.billing import benchmark, benchmark_playbook as playbook, benchmark_profiles as profiles
from cloud.billing import ledger
from cloud.billing.models import (
    BenchmarkRun,
    BenchmarkStep,
    BenchmarkStepEvent,
    BillableEvent,
    BillingJob,
    RatedCharge,
)

pytestmark = pytest.mark.asyncio


# ── Playbook coverage contract ────────────────────────────────────────────────

async def test_every_plugin_is_covered():
    assert playbook.uncovered_plugins() == []
    cov = playbook.coverage()
    for plugin in playbook.CORE_PLUGINS + playbook.MARKETPLACE_PLUGINS:
        assert cov[plugin], f"{plugin} has no playbook coverage"


async def test_catalog_shape():
    keys = [i.key for i in playbook.CATALOG]
    assert len(keys) == len(set(keys)), "duplicate item keys"
    for item in playbook.CATALOG:
        assert item.kind in playbook.KINDS
        if item.kind in ("chat", "chat_multi"):
            assert item.prompts, f"{item.key} has no prompts"
        if item.kind == "window":
            assert item.window_seconds > 0
    # The cheap smoke subset must be runnable by default.
    for key in playbook.SMOKE_KEYS:
        assert key in playbook.DEFAULT_KEYS


# ── Fake driver: emits billable events the way the gateway would ─────────────

class FakeDriver:
    """send_message writes one billable event (2 attempts: a failed one and
    the final) + its rated charge, mimicking gateway metering."""

    def __init__(self, db, run_account_id, run_agent_id, *, fail_items=()):
        self.db = db
        self.account_id = run_account_id
        self.agent_id = run_agent_id
        self.fail_items = set(fail_items)
        self.calls = 0
        self.orphan_on_login = False
        self.closed = False

    async def login(self):
        if self.orphan_on_login:
            await self._emit(call_id=f"orphan-{uuid.uuid4()}", credits=7)

    async def _emit(self, call_id, credits, vendor=50_000):
        now = datetime.now(timezone.utc)
        self.db.add(BillableEvent(
            source_idempotency_key=f"{call_id}:1", call_id=call_id,
            account_id=self.account_id, agent_id=self.agent_id,
            service="anthropic", sku="anthropic:messages", context="agent",
            provider="anthropic", model="claude-sonnet-5", attempt_number=1,
            quantity_json={"input_tokens": 100, "output_tokens": 0},
            vendor_cost_micro_usd=10_000, cost_source="provider_usage",
            status="recorded", event_at=now,
        ))
        self.db.add(BillableEvent(
            source_idempotency_key=f"{call_id}:2", call_id=call_id,
            account_id=self.account_id, agent_id=self.agent_id,
            service="anthropic", sku="anthropic:messages", context="agent",
            provider="anthropic", model="claude-sonnet-5", attempt_number=2,
            quantity_json={"input_tokens": 1_000, "output_tokens": 200,
                           "cache_read_input_tokens": 400,
                           "cache_creation_input_tokens": 50},
            vendor_cost_micro_usd=vendor, cost_source="provider_usage",
            status="recorded", event_at=now,
        ))
        self.db.add(RatedCharge(
            logical_call_id=call_id, account_id=self.account_id,
            vendor_cost_micro_usd=vendor + 10_000, margin_micro_usd=12_000,
            credits=credits, charge_status="settled",
        ))
        await self.db.flush()

    async def create_conversation(self, title):
        return f"conv-{title}"

    async def send_message(self, conversation_id, text):
        self.calls += 1
        item_key = conversation_id.removeprefix("conv-benchmark:")
        if item_key in self.fail_items:
            raise RuntimeError("agent exploded")
        await self._emit(call_id=f"call-{self.calls}", credits=20)
        return {"text": ""}

    async def api_reads(self):
        return None

    async def close(self):
        self.closed = True


async def _noop_sleep(_seconds):
    return None


async def _mk_run(db, account, agent, keys, repetitions=1):
    await ledger.ensure_billing_account(db, account.id)
    agent.config_overrides = {"benchmark": {"target": True}}
    await db.flush()
    run = await benchmark.start_run(
        db, agent=agent, created_by=None, item_keys=keys, repetitions=repetitions
    )
    run.state = "running"
    await db.commit()
    return run


# ── Runner ────────────────────────────────────────────────────────────────────

async def test_start_run_refuses_unflagged_agent(db_session, account, sample_agent):
    await ledger.ensure_billing_account(db_session, account.id)
    with pytest.raises(benchmark.BenchmarkError):
        await benchmark.start_run(db_session, agent=sample_agent, created_by=None)


async def test_start_run_creates_durable_job(db_session, account, sample_agent):
    await ledger.ensure_billing_account(db_session, account.id)
    sample_agent.config_overrides = {"benchmark": {"target": True}}
    run = await benchmark.start_run(db_session, agent=sample_agent, created_by=None)
    await db_session.commit()
    assert run.playbook_version == playbook.PLAYBOOK_VERSION
    assert list(run.item_keys) == list(playbook.DEFAULT_KEYS)
    job = (await db_session.execute(
        select(BillingJob).where(BillingJob.dedupe_key == f"benchmark:{run.id}")
    )).scalar_one()
    assert job.job_type == benchmark.BENCHMARK_JOB
    assert job.max_attempts == 1


async def test_execute_attributes_costs_and_trigger_log(db_session, account, sample_agent):
    run = await _mk_run(db_session, account, sample_agent,
                        ["chat.hello", "api.direct"], repetitions=2)
    driver = FakeDriver(db_session, account.id, sample_agent.id)
    driver.orphan_on_login = True  # fired during the run, inside no step window

    result = await benchmark.execute_run(
        db_session, run, driver, settle_seconds=0, sleeper=_noop_sleep
    )
    assert result["state"] == "succeeded"
    assert driver.closed is False  # closed by the job handler, not execute_run

    steps = (await db_session.execute(
        select(BenchmarkStep).where(BenchmarkStep.run_id == run.id)
        .order_by(BenchmarkStep.seq)
    )).scalars().all()
    by_key = {}
    for s in steps:
        by_key.setdefault(s.item_key, []).append(s)

    # chat.hello ran twice; each rep: 1 rated call of 20 credits, 2 attempts.
    assert len(by_key["chat.hello"]) == 2
    for s in by_key["chat.hello"]:
        assert s.status == "succeeded"
        assert s.credits == 20
        assert s.llm_requests == 2
        assert s.input_tokens == 1_100
        assert s.output_tokens == 200
        assert s.cache_read_tokens == 400
        assert s.cache_write_tokens == 50
        assert s.vendor_cost_micro_usd == 60_000
        assert s.margin_micro_usd == 12_000
        assert s.per_model["claude-sonnet-5"]["requests"] == 2

    # api.direct produced no billable events — reads are free.
    for s in by_key["api.direct"]:
        assert s.credits == 0 and s.llm_requests == 0

    # The login-time orphan landed in __background__, not lost.
    bg = by_key[benchmark.BACKGROUND_KEY][0]
    assert bg.credits == 7
    assert bg.llm_requests == 2

    # Trigger log: credits sit on the final attempt row only.
    events = (await db_session.execute(
        select(BenchmarkStepEvent).where(BenchmarkStepEvent.run_id == run.id)
    )).scalars().all()
    hello_step_ids = {s.id for s in by_key["chat.hello"]}
    hello_events = [e for e in events if e.step_id in hello_step_ids]
    assert len(hello_events) == 4
    assert sorted(e.credits for e in hello_events) == [0, 0, 20, 20]
    assert all(e.billable_event_id is not None for e in hello_events)
    assert all(e.quantities for e in hello_events)

    assert run.totals["credits"] == 47  # 2×20 + 7 background
    assert run.totals["background_credits"] == 7
    assert run.state == "succeeded"


async def test_failed_item_fails_run_but_not_other_steps(db_session, account, sample_agent):
    run = await _mk_run(db_session, account, sample_agent,
                        ["chat.hello", "chat.qa_short"], repetitions=1)
    driver = FakeDriver(db_session, account.id, sample_agent.id,
                        fail_items=["chat.qa_short"])
    result = await benchmark.execute_run(
        db_session, run, driver, settle_seconds=0, sleeper=_noop_sleep
    )
    assert result["state"] == "failed"
    steps = (await db_session.execute(
        select(BenchmarkStep).where(BenchmarkStep.run_id == run.id)
    )).scalars().all()
    by_key = {s.item_key: s for s in steps}
    assert by_key["chat.hello"].status == "succeeded"
    assert by_key["chat.qa_short"].status == "failed"
    assert "exploded" in by_key["chat.qa_short"].error
    assert run.totals["failed_steps"] == 1


async def test_abort_stops_between_steps(db_session, account, sample_agent):
    run = await _mk_run(db_session, account, sample_agent,
                        ["chat.hello", "chat.qa_short", "chat.generate_long"])
    driver = FakeDriver(db_session, account.id, sample_agent.id)

    async def abort_after_first(step):
        if step.seq == 1:
            run.state = "aborted"
            await db_session.flush()

    result = await benchmark.execute_run(
        db_session, run, driver, settle_seconds=0, sleeper=_noop_sleep,
        on_step_done=abort_after_first,
    )
    assert result["state"] == "aborted"
    assert result["steps_done"] == 1
    steps = (await db_session.execute(
        select(BenchmarkStep).where(BenchmarkStep.run_id == run.id)
    )).scalars().all()
    assert len(steps) == 1  # no further items, no background pass


async def test_unknown_item_rejected(db_session, account, sample_agent):
    await ledger.ensure_billing_account(db_session, account.id)
    sample_agent.config_overrides = {"benchmark": {"target": True}}
    with pytest.raises(benchmark.BenchmarkError):
        await benchmark.start_run(db_session, agent=sample_agent, created_by=None,
                                  item_keys=["chat.hello", "nope.nothing"])


# ── Profiles / projection ─────────────────────────────────────────────────────

def _step(key, credits, vendor=0, margin=0, status="succeeded", seconds=60):
    t0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    s = BenchmarkStep(
        run_id=uuid.uuid4(), seq=1, item_key=key, repetition=1, status=status,
        credits=credits, vendor_cost_micro_usd=vendor, margin_micro_usd=margin,
    )
    s.started_at = t0
    s.finished_at = t0 + timedelta(seconds=seconds)
    return s


async def test_item_medians_ignore_failures_and_background():
    steps = [
        _step("chat.hello", 10), _step("chat.hello", 20), _step("chat.hello", 30),
        _step("chat.hello", 999, status="failed"),
        _step("__background__", 500),
    ]
    m = profiles.item_medians(steps)
    assert m["chat.hello"]["credits"] == 20
    assert m["chat.hello"]["samples"] == 3
    assert "__background__" not in m


async def test_projection_math():
    steps = [
        _step("chat.hello", 20, vendor=60_000, margin=12_000),
        _step("web.search_summarize", 50, vendor=200_000, margin=30_000),
        # 1h idle sample burning 6 credits → 144/day.
        _step("background.idle", 6, vendor=20_000, seconds=3600),
    ]
    proj = profiles.project(
        steps,
        {"chat.hello": 30, "web.search_summarize": 10,
         profiles.BACKGROUND_ITEM: 30, "missing.item": 5},
        hosting_credits=999,
    )
    assert proj["missing_items"] == ["missing.item"]
    # 30×20 + 10×50 = 1100 metered + 144×30 = 4320 background
    assert proj["metered_credits"] == pytest.approx(1100 + 4320, abs=0.5)
    assert proj["monthly_credits"] == pytest.approx(1100 + 4320 + 999, abs=0.5)
    assert proj["monthly_revenue_micro_usd"] == pytest.approx(
        (1100 + 4320 + 999) * profiles.CREDIT_MICRO_USD, rel=1e-3)
    top = proj["per_item"][0]
    assert top["item_key"] == profiles.BACKGROUND_ITEM


async def test_presets_reference_real_items():
    for name, profile in profiles.PRESET_PROFILES.items():
        for key in profile:
            assert key in playbook.BY_KEY, f"{name} references unknown {key}"


# ── Admin API ─────────────────────────────────────────────────────────────────

SAME_ORIGIN = {"origin": "http://localhost:8100"}  # matches Settings.base_url


async def _audit_actions(db):
    from cloud.db.models import AuditLog
    rows = (await db.execute(select(AuditLog))).scalars().all()
    return [r.action for r in rows]


async def test_benchmark_api_requires_admin(regular_client, anon_client):
    assert (await regular_client.get("/api/admin/pricing/benchmark/playbook")).status_code == 403
    assert (await anon_client.get("/api/admin/pricing/benchmark/runs")).status_code == 401


async def test_playbook_endpoint_shape(admin_client):
    resp = await admin_client.get("/api/admin/pricing/benchmark/playbook")
    assert resp.status_code == 200
    body = resp.json()
    assert body["playbook_version"] == playbook.PLAYBOOK_VERSION
    assert body["uncovered_plugins"] == []
    assert set(body["presets"]) == {"light", "regular", "heavy"}
    keys = {i["key"] for i in body["items"]}
    assert set(body["smoke_keys"]) <= keys
    assert set(body["default_keys"]) <= keys


async def test_target_flag_flow(admin_client, db_session, account, sample_agent):
    url = f"/api/admin/pricing/benchmark/targets/{sample_agent.id}"
    # Reason required.
    assert (await admin_client.post(
        url, json={"target": True}, headers=SAME_ORIGIN)).status_code == 400
    # Flag on.
    resp = await admin_client.post(
        url, json={"target": True, "reason": "test rig"}, headers=SAME_ORIGIN)
    assert resp.status_code == 200 and resp.json()["target"] is True
    targets = (await admin_client.get("/api/admin/pricing/benchmark/targets")).json()["targets"]
    assert [t["id"] for t in targets] == [str(sample_agent.id)]
    # Flag off again.
    resp = await admin_client.post(
        url, json={"target": False, "reason": "done"}, headers=SAME_ORIGIN)
    assert resp.status_code == 200
    targets = (await admin_client.get("/api/admin/pricing/benchmark/targets")).json()["targets"]
    assert targets == []
    assert (await _audit_actions(db_session)).count("pricing.benchmark.target") == 2


async def test_run_start_refuses_unflagged_agent(admin_client, db_session, account, sample_agent):
    await ledger.ensure_billing_account(db_session, account.id)
    await db_session.commit()
    resp = await admin_client.post(
        "/api/admin/pricing/benchmark/runs",
        json={"agent_id": str(sample_agent.id), "reason": "x"}, headers=SAME_ORIGIN)
    assert resp.status_code == 400
    assert "not flagged" in resp.json()["detail"]


async def _flag_and_fund(admin_client, db_session, account, agent):
    await ledger.ensure_billing_account(db_session, account.id)
    await db_session.commit()
    resp = await admin_client.post(
        f"/api/admin/pricing/benchmark/targets/{agent.id}",
        json={"target": True, "reason": "test rig"}, headers=SAME_ORIGIN)
    assert resp.status_code == 200


async def test_run_lifecycle_via_api(admin_client, db_session, account, sample_agent):
    await _flag_and_fund(admin_client, db_session, account, sample_agent)

    resp = await admin_client.post(
        "/api/admin/pricing/benchmark/runs",
        json={"agent_id": str(sample_agent.id), "smoke": True,
              "repetitions": 2, "reason": "smoke pass"},
        headers=SAME_ORIGIN)
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["state"] == "pending"
    assert run["item_keys"] == list(playbook.SMOKE_KEYS)
    assert run["repetitions"] == 2
    assert run["agent_slug"] == sample_agent.slug

    listed = (await admin_client.get("/api/admin/pricing/benchmark/runs")).json()["runs"]
    assert [r["id"] for r in listed] == [run["id"]]

    detail = (await admin_client.get(
        f"/api/admin/pricing/benchmark/runs/{run['id']}")).json()
    assert detail["steps"] == [] and detail["medians"] == {}

    events = (await admin_client.get(
        f"/api/admin/pricing/benchmark/runs/{run['id']}/events")).json()["events"]
    assert events == []

    export = (await admin_client.get(
        f"/api/admin/pricing/benchmark/runs/{run['id']}/export")).json()
    assert export["id"] == run["id"] and export["steps"] == []

    # Abort, then abort again (idempotent on terminal state).
    resp = await admin_client.post(
        f"/api/admin/pricing/benchmark/runs/{run['id']}/abort", json={}, headers=SAME_ORIGIN)
    assert resp.status_code == 200 and resp.json()["state"] == "aborted"
    resp = await admin_client.post(
        f"/api/admin/pricing/benchmark/runs/{run['id']}/abort", json={}, headers=SAME_ORIGIN)
    assert resp.json()["state"] == "aborted"

    actions = await _audit_actions(db_session)
    assert "pricing.benchmark.run.started" in actions
    assert "pricing.benchmark.run.aborted" in actions


async def test_run_start_rejects_bad_input(admin_client, db_session, account, sample_agent):
    await _flag_and_fund(admin_client, db_session, account, sample_agent)
    base = {"agent_id": str(sample_agent.id), "reason": "x"}
    resp = await admin_client.post(
        "/api/admin/pricing/benchmark/runs",
        json={**base, "item_keys": ["nope.nothing"]}, headers=SAME_ORIGIN)
    assert resp.status_code == 400
    resp = await admin_client.post(
        "/api/admin/pricing/benchmark/runs",
        json={**base, "repetitions": 11}, headers=SAME_ORIGIN)
    assert resp.status_code == 422  # pydantic bound
    resp = await admin_client.post(
        "/api/admin/pricing/benchmark/runs",
        json={"agent_id": str(uuid.uuid4()), "reason": "x"}, headers=SAME_ORIGIN)
    assert resp.status_code == 404


async def test_projection_endpoint(admin_client, db_session, account, sample_agent):
    await _flag_and_fund(admin_client, db_session, account, sample_agent)
    run = (await admin_client.post(
        "/api/admin/pricing/benchmark/runs",
        json={"agent_id": str(sample_agent.id), "smoke": True, "reason": "x"},
        headers=SAME_ORIGIN)).json()

    resp = await admin_client.post(
        "/api/admin/pricing/benchmark/projection",
        json={"run_id": run["id"], "preset": "bogus"}, headers=SAME_ORIGIN)
    assert resp.status_code == 400

    resp = await admin_client.post(
        "/api/admin/pricing/benchmark/projection",
        json={"run_id": run["id"], "preset": "regular", "hosting_credits": 999},
        headers=SAME_ORIGIN)
    assert resp.status_code == 200
    proj = resp.json()
    # No steps yet: everything in the preset is missing, only hosting is priced.
    assert proj["monthly_credits"] == 999
    assert set(proj["missing_items"]) == {
        k for k in profiles.PRESET_PROFILES["regular"] if k != profiles.BACKGROUND_ITEM}

    resp = await admin_client.post(
        "/api/admin/pricing/benchmark/projection",
        json={"run_id": run["id"], "profile": {"chat.hello": 10}}, headers=SAME_ORIGIN)
    assert resp.status_code == 200
    assert resp.json()["missing_items"] == ["chat.hello"]


async def test_benchmark_mutations_reject_cross_origin(admin_client, sample_agent):
    resp = await admin_client.post(
        f"/api/admin/pricing/benchmark/targets/{sample_agent.id}",
        json={"target": True, "reason": "x"},
        headers={"origin": "https://evil.example"})
    assert resp.status_code == 403
