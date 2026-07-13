# Luna core changes for Luna Credits

**Status:** Proposal only; do not edit the `luna/` submodule from luna-service  
**Parent plan:** `plans/039-pricing-billing/PLAN.md`

## Bottom line

Luna core needs a small, general execution-metadata and proxy-error contract. It must not
own the hosted credit balance, pricing, Stripe, or enforcement.

The control-plane gateway already sits at the trusted provider boundary and must remain
the billing authority. Luna core only needs to:

1. classify each LLM request by its real execution path;
2. propagate correlation metadata and an opaque signed execution envelope to the proxy;
3. preserve provider-native usage details for local telemetry/cross-checking;
4. surface a gateway spending block as a typed, non-retryable UI/job result.

## Current code findings

### There are two different LLM paths

`luna/luna/agent/runtime.py`

- `LunaAgent.stream()` powers normal chat and uses Pydantic AI directly.
- `LunaAgent.run_turn()` powers headless agent/playbook work and also uses Pydantic AI
  directly.
- Both construct `Agent(...)` from provider/model strings and bypass `ModelRouter`.
- The final Pydantic AI usage is aggregate usage for the run, not a reliable per-provider
  request record.

`luna/luna/llm/utility.py` and `luna/luna/llm/router.py`

- `LunaAgent.run_llm()` delegates to `utility_complete()`.
- `utility_complete()` goes through `ModelRouter.complete()`.
- Memory, onboarding, condensation, and plugin utilities also use this path.
- `ModelRouter.complete()` logs `llm.called` before provider execution; it does not emit a
  completed billing-grade event with native usage.
- `utility_complete()` emits `llm.utility_call` after the stream, but this is best-effort
  local telemetry and exceptions are intentionally swallowed.

Therefore adding a field only to `ModelRouter.complete()` would miss normal chat and
headless agent steps. The shared contract must cover Pydantic AI and the custom router.

### Usage is currently too narrow

`luna/luna/types.py`

`Usage` currently contains only:

- `input_tokens`;
- `output_tokens`;
- estimated `cost_usd`.

`luna/luna/llm/providers/anthropic.py` and `openai.py`

- provider response usage is collapsed to normal input/output counts;
- Anthropic cache creation/cache-read and service-tier dimensions are not preserved;
- OpenAI cached/reasoning/audio/image dimensions are not preserved;
- embedding usage is not returned by the router contract;
- `cost_usd` comes from Luna's local mutable estimate, not a versioned hosted price.

The hosted gateway can parse the authoritative upstream response itself. Luna's expanded
usage is useful for local cost tools, debugging, and reconciliation, but must not become
the hosted financial source of truth.

### Proxy routing already exists

`luna/luna/config/schema.py` and `luna/luna/llm/router.py`

- hosted provisioning can inject provider API keys and provider-specific base URLs;
- the custom Anthropic/OpenAI providers already accept `base_url`;
- Pydantic AI reads mirrored provider credentials/environment.

This means the service does not need to replace Luna's model APIs. It needs a reliable
per-request metadata/header layer on both client implementations.

### The existing Phase 018 plan is not an implementation

`luna/plans/018-cost-rate-limiter/PLAN.md` proposes `plugin-cost`,
`plugin-rate-limiter`, `llm.before_call`, and richer `llm.called` payloads, but the current
tree does not provide those as a billing authority.

Even after implemented, a local plugin is appropriate for standalone/BYOK user budgets.
It cannot enforce the hosted shared account wallet because:

- the tenant process is outside the trusted billing boundary;
- it does not own Stripe grants or other Lunas' spending;
- it can be disabled or modified;
- it cannot authoritatively see all control-plane resources.

## Trust boundary

```text
Luna process (tenant boundary)
    │ agent-scoped proxy token
    │ advisory call metadata
    │ opaque signed execution envelope when available
    ▼
luna-service gateway (trusted billing boundary)
    │ real provider key
    │ atomic authorize / meter / rate / settle
    ▼
Provider
```

Luna must never decide whether the account can spend. A local pre-call hook may support a
standalone user's personal limit, but the hosted gateway independently authorizes every
platform-funded call.

## Proposed generic Luna API

### 1. Add one metering seam for both LLM paths

Add a `HookedModel`/instrumented-model wrapper around Pydantic AI `Model.request()` and
`request_stream()`, and use it in `_build_reasoning_model()` and the headless
`run_turn()` model path.

The custom `ModelRouter.complete()`/`embed()` path must call the same lifecycle helper.
One internal emitter/contract therefore covers:

- normal chat and tool-loop model nodes;
- playbook agent steps;
- utility/summarization calls;
- embeddings;
- fallback attempts.

The wrapper owns correlation, per-attempt lifecycle events, provider request metadata,
and typed policy-error mapping. It may expose a generic pre-call hook for standalone
limits, but hosted authorization remains mandatory in the gateway.

### 2. Add a request-scoped LLM call context

Add a small module such as `luna/luna/llm/context.py`:

```python
class LLMCallKind(StrEnum):
    AGENT = "agent"    # any agentic loop: chat, playbook agent steps, background runs
    DIRECT = "direct"  # single one-shot calls: llm_step, utilities, summarization
    FORGE = "forge"    # coding-agent calls inside a Forge job

@dataclass(frozen=True)
class LLMCallContext:
    logical_call_id: UUID
    root_action_id: UUID | None
    kind: LLMCallKind
    caller: str
    execution_envelope: str | None = None
```

Provide a `ContextVar`, getter, and async/sync context manager:

```text
llm_call_scope(kind, caller, root_action_id=None, execution_envelope=None)
```

Rules:

- every Luna request for one model result gets a new `logical_call_id`;
- every provider/fallback attempt under it gets a separate `attempt_id`;
- child logical calls inherit `root_action_id`;
- context is task-local and safe under concurrent async turns;
- nested utility calls may replace `kind` while preserving root action;
- absent context defaults to `agent`, the most expensive class;
- no account ID, price, balance, or Stripe data enters this object.

### 3. Tag every core call path explicitly

Do not infer context from prompt text, model, or stack traces.

`LunaAgent.stream()`

- opens an `agent` scope for the root user turn;
- preserves the conversation/root-action correlation across model/tool/model loops;
- each Pydantic AI model node receives a unique logical-call ID;
- provider fallbacks for that node retain the logical-call ID and get unique attempt IDs.

`LunaAgent.run_turn()`

- gains an explicit `caller` argument for functional attribution;
- always runs an agentic loop, so every caller (playbook `agent_step`,
  muted/background/reaction paths) is `agent`.

`LunaAgent.run_llm()` and `utility_complete()`

- gain explicit `call_kind` and `root_action_id`;
- these are one-shot calls: playbook `llm_step`, condensation/memory summarization, and
  other utilities pass `direct`;
- a utility that itself runs a loop passes `agent`.

`ModelRouter.embed()`

- propagates the current scope;
- emits unique logical-call/attempt IDs and preserves embedding-native usage when the
  provider exposes it.

Forge and future job runners:

- open a `forge` scope at job entry;
- all LLM child calls inherit the Forge root action/job ID.

Add a test/grep invariant listing every direct Pydantic AI/provider construction site.
New call paths must either open a scope or deliberately inherit one.

### 4. Propagate headers through both HTTP stacks

Every proxy-bound provider request should include:

```text
X-Luna-Logical-Call-Id
X-Luna-Attempt-Id
X-Luna-Root-Action-Id
X-Luna-Call-Context
X-Luna-Caller
X-Luna-Execution-Envelope   # only when present
```

The exact names are part of a versioned service/core contract.

Implementation requirements:

- use a shared request transport/interceptor that reads the task-local context at send
  time;
- apply it to explicit Anthropic/OpenAI/OpenRouter clients and Pydantic AI models;
- preserve configured base URLs, normal provider headers, streaming, retries, and BYOK;
- do not mutate process-wide environment or global headers per request;
- do not put prompts, output, tool arguments, or user identity in headers;
- local/direct provider operation remains valid when no hosted proxy is configured;
- gateways that do not understand the headers safely ignore them.

Because normal chat uses Pydantic AI model strings today, the implementation will likely
need to build explicit Pydantic AI provider/model objects with the shared HTTP client
rather than relying only on strings. Verify the installed Pydantic AI provider API before
coding; do not monkey-patch SDK internals.

### 5. Carry an opaque signed execution envelope

**Deferred at launch.** With the agent/direct/forge scheme, model tier and forge are
gateway-verified and an unknown context rates as `agent` (the most expensive class), so
the envelope only guards against agent→direct misdeclaration — bounded at the constant
spread per call. Ship the transport hook, but envelope minting/verification is built only
if reconciliation shows material leakage.

`luna-service` creates and verifies the envelope. Luna core only transports it.

Envelope claims owned by the service:

- issuer/audience and contract version;
- account and Luna IDs;
- root action/run ID;
- allowed call kind;
- issued-at/expiry;
- nonce/key ID.

Ingress middleware may place a verified-but-opaque envelope into the Luna call context.
Internal runners may receive one explicitly from their trusted caller. Luna must not
parse, alter, refresh, or mint it.

The gateway rules are:

- model tier and forge job identity are always gateway-verified;
- missing/invalid context → `agent`, the most expensive class;
- at launch, a raw `direct` header is accepted as declared (bounded leakage); once
  envelope hardening is enabled, a cheaper context requires a valid envelope.

This protects normal chat, signed relays, scheduler runs, and Forge jobs. It does not
claim remote attestation of arbitrary code inside a tenant machine; the parent plan keeps
a safe default/floor for that reason.

## Provider lifecycle events

Replace the ambiguous "called before anything happened" meaning with explicit
per-attempt events and one logical completion:

### `llm.attempt.started`

- logical-call/attempt/root-action IDs;
- kind/caller;
- requested provider/model/purpose;
- timestamp;
- no content.

### `llm.attempt.completed`

- same correlation fields;
- actual provider/model for this attempt;
- provider request/response ID when available;
- normalized aggregate usage;
- provider-native usage details;
- latency and finish reason.

### `llm.attempt.failed`

- same correlation fields;
- provider/model/attempt;
- safe error class/status/retryability;
- whether provider usage may have occurred.

### `llm.completed` / `llm.failed`

- emitted once when the logical call returns a usable result or finally fails;
- logical/root-action IDs, kind/caller, and selected provider/model;
- all attempt IDs and normalized provider-billable usage;
- one stable event for local cost tools to apply a per-logical-call policy.

Compatibility:

- retain legacy events during one deprecation window if existing plugins consume them;
- document whether `llm.called` aliases attempt-start or logical-complete;
- local plugins dedupe on logical-call and attempt IDs;
- event delivery remains telemetry, not a hosted settlement dependency.

## Expand local usage without making it financial authority

Extend `Usage` or add `ProviderUsage`:

```text
input_tokens
output_tokens
cache_creation_input_tokens
cache_read_input_tokens
cached_input_tokens
reasoning_output_tokens
audio_input_tokens
audio_output_tokens
image_units
embedding_tokens
native_details
provider_request_id
```

Rules:

- preserve raw provider-native integer dimensions under a namespaced structure;
- avoid double counting reasoning that is already included in output;
- avoid calculating hosted customer credits in Luna;
- keep local estimated cost explicitly labeled as an estimate;
- the gateway/provider report remains authoritative for hosted settlement.

Pydantic AI runs must emit one attempt record per actual provider request and one logical
completion, not only one aggregate record after a multi-model/tool run.

## Typed spending-block behavior

### Gateway response

The hosted gateway returns a stable non-retryable error, for example:

```json
{
  "code": "credits_exhausted",
  "scope": "account",
  "balance_credits": -5,
  "required_action": "top_up",
  "action_url": "/dashboard/billing",
  "request_id": "..."
}
```

Other codes include Luna daily/monthly limits, hosting payment due, and unpriced SKU.

### Luna core mapping

Add a generic typed exception such as `ProviderPolicyBlockedError`:

- safe `code`, `scope`, optional numeric limit/current value;
- `retryable = false`;
- optional operator-provided action label/URL;
- no hosted ledger or Stripe implementation.

Both custom providers and Pydantic AI error paths must map the gateway's status/body to
this exception before normal fallback logic.

Rules:

- do not try another provider when the gateway blocked account spending;
- do not ask another LLM to explain the block;
- chat emits a structured terminal event that UI can render;
- headless playbook/job execution returns a typed blocked result;
- the control plane can translate the action URL at the proxy boundary;
- generic provider rate limits continue through normal fallback policy.

### Luna UI

Add a generic action-required banner/card:

- title/message from a safe code mapping;
- optional current/limit credits;
- optional `Top up`/`Manage limits` link supplied by the host;
- no dollars or internal provider economics;
- no traceback and no retry loop.

Standalone Luna can render "provider usage policy blocked this request" when no hosted
action URL exists.

## What stays entirely in luna-service

Do not add any of these to Luna core:

- account wallet or grant lots;
- recurring/bonus/free/gift/top-up products;
- pricing versions or fixed margin values;
- Stripe customer/subscription/payment/webhook code;
- account or cross-Luna limits;
- holding, settlement, debt, or ledger logic;
- per-Luna 999-credit hosting periods;
- provider-key pool or real platform credentials;
- customer cash/margin dashboard;
- admin pricing editor or simulator;
- provider invoice reconciliation;
- marketplace seller accounting.

Luna may keep a separate local/BYOK cost plugin. Its UI must not present local estimates
as the hosted account balance.

## Delivery plan in the Luna repository

This work must be proposed and executed in the Luna repository's own numbered plan and
dev process, not edited through the luna-service submodule.

### Luna phase 1 — Context and transport

Starts with a **spike**: reasoning/chat/headless paths currently build Pydantic AI
models from strings (`_build_reasoning_model()` in `luna/luna/agent/runtime.py`), so
per-request headers cannot ride on static client config. The spike builds explicit
`AnthropicModel`/`OpenAIModel` provider objects with httpx `event_hooks` that read the
ContextVar at send time, and proves it with one streamed chat and one `utility_complete`
call before the rest of the phase proceeds. Pin `pydantic-ai` to a tested minor version
(`pyproject.toml` currently allows `>=0.0.14` — too loose while the client lifecycle is
in flux).

- add context types/scope;
- define the root-action mint table and set it in transport: chat turn → user message
  UUID; playbook run → run ID; scheduled/background job → job ID; continue/overflow
  retry → same root action; post-turn condensation → inherits the chat root with a new
  logical call. `stream()` entry and the playbook runner entry set the ContextVar; child
  logical calls inherit it;
- add the shared `HookedModel`/lifecycle helper across Pydantic AI and `ModelRouter`.
  Placement is mandated: the wrapper goes **around the entire `FallbackModel`**, so a
  fallback chain shares one logical-call ID; every inner `request()`/`request_stream()`
  (each actual provider HTTP attempt) gets a new attempt ID. `HookedModel` creates a new
  logical-call ID per top-level `Model.request()`/`request_stream()` invocation, which
  yields one logical call per model node in a tool loop;
- add `ProviderPolicyBlockedError(retryable=False)` **in this phase**, before events and
  UI: the custom router currently maps unknown 4xx (including a future 402) to retryable
  `ProviderDownError` (`luna/luna/llm/providers/anthropic.py`), so a credit block would
  trigger a second provider/key. Parse the gateway block JSON in the custom providers and
  in the Pydantic AI `ModelHTTPError` path, and short-circuit before
  `should_fallback()` / `FallbackModel.fallback_on`;
- build shared task-local header transport;
- make custom providers and explicit Pydantic AI models use it;
- preserve existing config/base URL/model fallback behavior;
- add concurrency and header contract tests.

Exit: every logical call and provider attempt has a unique ID and explicit/default
context, with no cross-talk between concurrent runs; a synthetic 402 causes no fallback.

### Luna phase 2 — Call-site classification and events

- tag chat, playbook agent steps, playbook LLM steps, background, summarization, and
  embeddings. The caller inventory additionally includes the sites the original list
  missed: CLI one-shot (`luna/luna/cli.py`, `direct` or out of hosted scope), onboarding
  persona (`luna/luna/onboarding/service.py`, `direct`), memory forget-verify
  (`plugin_memory`, `direct`), post-turn condensation task (`direct`, nested under the
  chat root action), overflow-retry second `stream()` (same root action, new logical
  calls), and embeddings (`router.embed`, `direct`);
- **Forge tagging is deferred** until the Forge runner exists (plan 034) — no `forge`
  scope or tests in Luna until then; the gateway forge-token design stays in 034/004 and
  the SKU stays seeded disabled;
- publish a provider support matrix: each provider/path is `hosted-metered`,
  `BYOK-only`, or `unsupported`; no unlisted provider is considered covered.
  Gemini/Ollama currently bypass the proxy (no base_url mirroring) — hosted enforce mode
  fails closed for non-proxy providers at the gateway/catalog, not in Luna;
- emit lifecycle events per provider attempt and completion/failure per logical call;
- expand provider-native usage details, including embedding token counts where the
  provider exposes them (`OpenAIProvider.embed()` currently returns vectors only) and
  attempt-completed events for embed logical calls;
- keep backward-compatible event aliases for one release, with an explicit alias table:
  `llm.called` (fires pre-execution today) and `llm.utility_call` map to named new
  events or a deprecated shim, and the Phase 018 `plugin-cost` plan is listed as a
  migration consumer.

Exit: a fixture containing chat → tool → second model call plus a summarization child
produces correctly grouped, individually identified events.

### Luna phase 3 — Policy-block propagation and UI

Precondition: the gateway block JSON schema and HTTP status are **frozen in
luna-service phase 004 before this phase's E2E tests** — today's gateway returns 403
`{"error":{"type":"forbidden"}}` while the plan specifies 402 + block codes; the two
must be aligned in one contract.

- map gateway policy errors in both provider stacks (the typed error itself lands in
  phase 1);
- prevent fallback/retry for policy blocks;
- return structured terminal events/results: add `AgentEvent(kind="policy_blocked")` and
  a matching SSE event — the current kinds
  (`delta|tool_call_started|tool_result|turn_done|notice|done`) have no block type, and
  the UI currently renders SSE errors as generic markdown error text;
- render generic action-required UI, with `action_url` from the host env
  (`LUNA_HOST_NAME`/dashboard base already provisioned);
- test hosted and standalone behavior.

Exit: a 402 credit block makes no provider retry, shows a usable banner, and returns a
typed blocked result to headless callers.

## Luna tests

### Unit

- default context is `agent`;
- nested scopes preserve root action and create unique logical calls/attempts;
- concurrent async tasks never leak kind/envelope/correlation;
- headers contain no prompt/output data;
- invalid/missing envelope is forwarded as absent, never fabricated;
- provider-native usage parsing covers cache/reasoning/audio/embedding fixtures;
- policy block is non-retryable and distinct from provider 429.

### Integration

- normal streamed chat sends `agent` metadata on every model node;
- tool loop has one root action, distinct logical calls, and distinct attempt IDs;
- `run_turn()` from playbook sends `agent`;
- `llm_step` sends `direct`;
- condensation/memory utility sends `direct`;
- background/muted path sends `agent`;
- CLI one-shot, onboarding persona, memory forget-verify, and post-turn condensation
  send `direct`; overflow retry keeps the root action with new logical calls;
- Forge child calls send `forge` (deferred until the Forge runner exists);
- Pydantic and custom-router fallback attempts share a logical ID and differ in attempt
  ID; cancellation does not leak ContextVars into the next task;
- unclassified call defaults to `agent`;
- Anthropic, OpenAI, OpenRouter, and Pydantic AI paths all propagate metadata;
- BYOK/direct provider mode still works without an envelope;
- fallback events record each actual attempt.

### End-to-end with luna-service

- chat rates as `agent` at the verified model tier of the requested model;
- playbook `llm_step` declaring `direct` rates as `direct`; missing/invalid context
  rates as `agent`;
- a forge job token rates as `forge` regardless of headers;
- logical-call/attempt IDs correlate gateway events, rated charge, and customer root
  action;
- zero/negative balance returns one structured block and contacts no provider;
- Luna daily/monthly block is rendered correctly;
- top-up makes the next request succeed without reprovisioning;
- no content or credential reaches billing records.

## Compatibility and rollout

1. Ship luna-service support for missing metadata first; it rates missing context as
   `agent`.
2. Ship Luna core changes with optional/default arguments and ignored-by-default headers.
3. Build a new hosted Luna image and canary it.
4. Compare gateway-observed call counts/contexts with Luna lifecycle events.
5. Require the compatible image before enabling context-specific constants for hosted
   accounts.
6. Keep `agent` as the safe fallback for old images.
7. Remove legacy event aliases only after local plugin consumers migrate.

## Definition of done

- Every Luna LLM path has an explicit or safe-default context.
- Pydantic AI and custom router requests carry the same contract.
- Correlation distinguishes root actions, logical calls, and provider attempts.
- Verified dimensions (model tier, forge job token) control price variance; unknown
  context defaults to the most expensive class; the signed envelope is deferred
  hardening.
- Hosted enforcement remains entirely in luna-service.
- Provider-native usage is available for local telemetry without being trusted as hosted
  money.
- Credit/limit blocks are non-retryable, structured, and useful in chat and headless runs.
- Standalone/BYOK Luna behavior remains intact.
