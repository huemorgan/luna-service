# 039/003 — Luna core metering contract

**Parent:** `plans/039-pricing-billing/luna-core-plan.md`
**Depends on:** nothing in luna-service — runs in parallel with 001/002
**Executed in:** the Luna repository, as its own numbered plan and dev process. The
`luna/` submodule is never edited from luna-service. This folder tracks the dependency;
the detailed spec lives in `luna-core-plan.md`.

## Objective

Give every Luna LLM call an explicit context (`agent`/`direct`/`forge`), correlation IDs
(root action → logical call → provider attempt), header transport to the gateway, richer
provider-native usage telemetry, and typed non-retryable handling of gateway spending
blocks. No billing logic enters Luna core.

## Sub-phases (in the Luna repo)

### 3.1 Context and transport

- Opening spike: explicit Pydantic AI provider/model objects (chat/reasoning paths use
  model strings today) with httpx `event_hooks` reading the ContextVar at send time;
  pin `pydantic-ai`; prove with one streamed chat + one utility call.
- `LLMCallKind` (`agent`/`direct`/`forge`) + `LLMCallContext` with ContextVar scope.
- Root-action mint table (chat message UUID / playbook run ID / job ID) set at
  `stream()` and playbook-runner entry.
- `ProviderPolicyBlockedError(retryable=false)` lands here — before fallback logic —
  so a gateway 402 can never trigger a provider fallback (the router currently maps
  unknown 4xx to retryable `ProviderDownError`).
- `HookedModel` wraps the entire `FallbackModel`: one logical-call ID per chain, one
  attempt ID per actual provider HTTP request, new logical ID per model node.
- `HookedModel`/lifecycle wrapper covering both LLM paths: Pydantic AI
  (`stream()`/`run_turn()`) and `ModelRouter.complete()/embed()`.
- Shared task-local header transport (`X-Luna-Logical-Call-Id`, `X-Luna-Attempt-Id`,
  `X-Luna-Root-Action-Id`, `X-Luna-Call-Context`, `X-Luna-Caller`) applied to explicit
  provider clients and Pydantic AI models; no prompts/output/user identity in headers.
- Absent context defaults to `agent`. Envelope transport hook only — minting/verification
  is deferred hardening (see luna-core-plan §5).

Exit: every logical call and attempt has unique IDs and explicit/default context, no
cross-talk between concurrent async runs.

### 3.2 Call-site classification and events

- Tag call sites: `stream()` and all `run_turn()` callers → `agent`; playbook
  `llm_step`, condensation/summarization, one-shot utilities, CLI one-shot, onboarding
  persona, memory forget-verify, embeddings → `direct`. Forge tagging is deferred until
  the Forge runner exists (plan 034).
- Provider support matrix: every provider/path declared `hosted-metered`, `BYOK-only`,
  or `unsupported`; Gemini/Ollama bypass the proxy today and fail closed at the gateway
  in hosted enforce mode.
- Lifecycle events: `llm.attempt.started/completed/failed`, `llm.completed/failed` per
  logical call; legacy event aliases for one release.
- Expand `Usage`/`ProviderUsage` with cache/reasoning/audio/embedding/native dimensions;
  local cost stays labeled an estimate, never hosted financial authority.
- Grep/test invariant listing every direct provider construction site.

Exit: a chat → tool → second-model fixture plus a summarization child produces correctly
grouped, individually identified events.

### 3.3 Policy-block propagation and UI

- Precondition: gateway block JSON + HTTP status frozen in 004 first (today's gateway
  returns 403 `forbidden`, not the 402 block contract).
- Map gateway block responses (`credits_exhausted`, limits, `hosting_payment_due`,
  `sku_unpriced`, `exposure_limit`) via the typed `ProviderPolicyBlockedError` from 3.1
  in both provider stacks; add `AgentEvent(kind="policy_blocked")` + SSE event (no block
  kind exists in the current event union).
- No provider fallback and no LLM-generated explanation on a policy block.
- Chat renders an action-required banner (host-supplied top-up/limits URL); headless
  runs return a typed blocked result. Standalone/BYOK behavior unchanged.

Exit: a 402 credit block makes no provider retry, shows a usable banner, and returns a
typed blocked result to headless callers.

## Amendments from phase 001 (2026-07-13)

- The ledger's idempotency scheme is fixed: operation ID + canonical sha256 of the
  sorted-key JSON request facts; same ID with a different hash is a hard conflict, never
  a dedupe. Luna's correlation IDs (`X-Luna-Logical-Call-Id`, attempt, root action) must
  therefore be stable across Luna-side retries of the *same* logical call and fresh for
  new ones — the gateway derives charge idempotency from them (004).

## Coordination with luna-service

1. luna-service ships first and rates missing metadata as `agent` (004 does not wait).
2. Luna changes ship with optional/default arguments and ignored-by-default headers.
3. Build a hosted Luna image, canary it, compare gateway-observed contexts with Luna
   lifecycle events.
4. Context-specific constants for hosted accounts are enabled only after the compatible
   image is required (rollout step in 010).

## Exit criteria

- Luna repo plan for all three sub-phases merged and released in a hosted image.
- E2E against luna-service: chat rates `agent` at the verified model tier; `llm_step`
  declaring `direct` rates `direct`; missing context rates `agent`; forge job token
  rates `forge` regardless of headers; blocks render without provider retries.

## Amendments from phase 002 (2026-07-14)

- Version snapshotting is interval-based: 002 shipped a gapless, append-only
  assignment chain per account (PG exclusion constraint `excl_cpa_no_overlap`
  guarantees no overlap). A rollout mid-conversation changes pricing only for
  logical calls that start after the effective time — no Luna-side work, but
  the E2E canary in the exit criteria should include a version-rollout flip to
  confirm in-flight calls keep their snapshot.
- Tier coverage is enforced at publish time only; a gateway model enabled
  after a version is published is unpriced under that active version and the
  gateway fails closed with `sku_unpriced`. Treat `sku_unpriced` as an
  expected runtime state during model rollouts in 3.3's block handling, not an
  operator-only anomaly.
