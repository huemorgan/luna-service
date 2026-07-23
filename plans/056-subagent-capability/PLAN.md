# 056 — Subagent capability: isolated delegated loops + pareto subagents

## Context

Luna has exactly one reasoning loop per conversation. Everything the agent
does — every tool result, every intermediate step — lands in the one context
window, defended only by caps/stubs/condense (see 055). Plan 055 Phase 04
(reader subagent) needs a second, isolated loop; that primitive doesn't
exist. This plan builds it once and picks the pareto set of subagents to run
on it.

The runtime is closer than it looks: `LunaAgent` is already constructable
with an injected tool registry and model override
(`luna/agent/runtime.py:860`), `_FilteredToolRegistry` (`runtime.py:810`)
already provides restricted read-only registry views, `llm_call_scope`
nesting (`luna/llm/context.py:59`) already attributes nested LLM calls to the
parent root action (billing/metering falls out for free), and `MAX_TURNS`
already bounds a loop. What's missing is a supervised wrapper: fresh message
list, budget, timeout, kill switch, and a typed result.

## Design — the primitive

```python
result = await run_subagent(
    task="Find the refund policy in these 3 PDFs; quote exact lines.",
    tools=["read", "web_search"],        # allowlist → _FilteredToolRegistry view
    model=None,                          # default: summarization chain (Haiku);
                                         # caller may pin the reasoning model
    max_turns=8,                         # << MAX_TURNS; subagents are errands
    token_budget=30_000,                 # hard: loop aborts, partial returned
    timeout_s=120,
    context=[...],                       # optional seed messages (doc handles, not dumps)
)
# -> SubagentResult(text, structured: dict|None, usage: RunUsage, aborted: bool)
```

Rules:

- **Isolation**: fresh `LunaAgent` instance, fresh message list, own minimal
  system prompt ("you are a single-purpose errand runner; your final text is
  the return value, not a user-facing message"). No memory writes, no
  outbound sends — the tool allowlist enforces both.
- **Attribution**: runs inside `llm_call_scope(kind=DIRECT)` under the
  parent's root action — costs bill to the turn that spawned it, same as
  condense does today. UI event bus gets `subagent.started/finished` so the
  chat shows a progress chip instead of silence.
- **Containment**: `max_turns`, `token_budget`, `timeout_s` are hard; on any
  breach return `aborted=True` with whatever partial text exists. Parent
  decides whether partial is usable. No nesting (a subagent cannot spawn
  subagents) in v1.
- **Return path**: only `result.text`/`structured` enters the parent context
  — the subagent's transcript is logged (structlog + cost events) and
  discarded. This is the whole point.
- Internal-only at first: features call `run_subagent`; the reasoning agent
  does NOT get a generic `delegate` tool until we've watched real usage
  (a self-delegating consumer agent is a runaway-cost surface).

## Pareto subagents (value ÷ effort, ranked)

1. **Reader** (055 Phase 04) — "go find X in these sources", multi-doc,
   returns answer + exact quotes with refs. Tools: `read` + search. First
   consumer of the primitive; ships with it.
2. **Web researcher** — "find/compare/decide" over multiple pages: search,
   fetch, synthesize; giant page dumps stay out of the main window. Biggest
   consumer-visible win (travel, shopping, comparisons). Tools: web search +
   fetch + `read`.
3. **Outbound verifier** — before an irreversible send (email, purchase,
   marketplace order), a cheap critic checks the draft against the user's
   actual ask + conversation record and returns pass/objections. Piggybacks
   the 047 approval flow; catches wrong-recipient / wrong-amount / scope
   drift. Tiny effort (often max_turns=1–2), outsized trust win.
4. **Playbook step isolator** — goalseek/scheduler steps that chain many
   tools currently spam the owning conversation's history (the 1.86M-char
   playbook-status incident). Run each step as a subagent; the conversation
   records outcome + handle. Medium effort (touches playbook runner), big
   context-hygiene win.
5. **Memory curator** — off-turn housekeeping: dedupe/expire/merge memory
   facts on a schedule. Low urgency; needs no new infra beyond the
   primitive + a cron hook. Do last.

Not worth it now: coder/CI subagents (not our product), semantic-index
builder (055 "later"), multi-agent debate/panels (cost without a consumer
story).

## Phases

- [ ] 01 — `run_subagent` primitive + containment tests (budget/turn/timeout
      breach, tool allowlist escape attempts, attribution assertions)
- [ ] 02 — Reader subagent wired as 055's escalation tier (unblocks 055/04)
- [ ] 03 — Web researcher behind a config flag; measure token delta vs
      inline fetching on real conversations
- [ ] 04 — Outbound verifier hooked into the approval path
- [ ] 05 — Playbook step isolation
- [ ] 06 — Decide on an agent-facing `delegate` tool + memory curator, with
      usage data from 02–05

## Status

Plan drafted 2026-07-23; awaiting Roy review. 055 keeps Phases 01–03
(read tool, query mode, handles) and delegates its Phase 04 here.
