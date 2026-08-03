# 070 — Qwen (Alibaba DashScope) provider: execution report

Date: 2026-08-03. Plan: `luna/plans/070-qwen-provider/PLAN.md`.

## Delivered

- **Provider**: `qwen` — DashScope intl compatible-mode (`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`), OpenAI-chat shape, routed through the billed gateway (`/proxy/qwen/*`). No `prompt_cache_key` sent (DashScope support unverified; unknown body params risk upstream 400s) — DashScope's implicit cache still reports `prompt_tokens_details.cached_tokens`.
- **Models** (best-for-agents/code picks per plan):
  - `qwen3.8-max` — "Qwen3.8 Max", flagship, top tier.
  - `qwen3-coder-next` — "Qwen3 Coder Next", agentic coder, mid tier.
  - `qwen3.7-flash` — "Qwen3.7 Flash", cheap/fast, mid tier.
- **Luna core 0.65.000** (`9f01f238`): QwenProvider (router `_KEYED_PROVIDERS` + `_make_provider`), runtime base-url default + cache tripwire, picker ranks (`qwen:` trio in `modelRanks.ts`), provider order `openai > anthropic > moonshot > qwen > xai > gemini`. Dojo test added in `b22df088`.
- **luna-service** (`5c234ba`): qwen gateway service (seeded on deploy, `provision_by_default`), billed route, 3 seeded models, rates, tiers.
- **luna-marketplaces** (`34e2904`): plugin-chat-ui **0.5.0** rebuilt against 0.65.000 (qwen ranks + group), published to the official marketplace.

## Production rollout

- Qwen API key added to the gateway key pool via admin API only (key id `5db01fd7`, key_count 1 on all 3 models). **Never committed** — `grep -rn "sk-ws-"` scan clean before every commit.
- Provider-cost **v9** (`49162ea9`) and commercial **v9** (`9727bd09`, "qwen-provider-070") published.
- **Pricing rollout required**: publishing v9 did NOT move accounts (assignments pin accounts to the version at their last rollout → 402 `sku_unpriced` on qwen). Fixed via `POST /api/admin/pricing/rollouts` `{version_id, audience: all_accounts}` → rollout `42297ca7`, billing job completed **24/24 accounts, 0 failed**.
- **Fleet**: image 0.65.000 (build `0bc849d6`) — test-agent passed, set-main, 35/35 machines migrated. Env backfill `LUNA_QWEN_API_KEY` + `LUNA_QWEN_BASE_URL=https://luna.com.ai/proxy/qwen` complete; `LUNA_MODEL_CATALOG` push 34 OK / 0 failed. `nave-my-luna-2` was stopped pre-op and left stopped.
- **Tenant chat-ui**: 34/34 started tenants upgraded to 0.5.0, 0 failed.

## Dojo browser test — 14/14 PASS

`luna/dojo/tests/070-qwen-provider/walkthrough.mjs` against prod `vaselin-gamer` through the CP proxy: chat-ui 0.5.0 live, groups contiguous + ordered (`openai>anthropic>moonshot>qwen>xai`, 4 dividers), trio present with pips (Max q5/s3/c1, Coder Next q4/s4/c1, Flash q3/s5/c1), 13 ranked rows with no 0-pip highlights, default switched to Qwen3 Coder Next, **live chat round-trip ("pong" assistant bubble on screenshot)**, default restored. Artifacts in `luna/dojo/results/070/`.

Two walkthrough fixes made during the run:

1. chat-ui 0.5.0 renders picker rows as `div[tabindex=0]`, not `<button>` (the 063-era locator failed) — selectors updated.
2. The original "pong" detector could match the user's own bubble; replaced with a baseline-count check (occurrences must grow after send), verified against the screenshot.

## Billing E2E — PASS (3 settled charges, no bypass)

Direct `rated_charges` query (temp DB allowlist, reverted to `[]` and verified):

| when (UTC) | path | credits | status | vendor cost µUSD | margin µUSD |
|---|---|---|---|---|---|
| 13:07:45 | curl `POST /proxy/qwen/chat/completions` (13 in / 2 out) | 2 | settled | 4 | 10,000 |
| 13:15:42 | dojo run 1 agent chat (~70k ctx) | 2 | settled | 7,723 | 10,000 |
| 13:18:12 | dojo run 2 agent chat (cached ctx) | 2 | settled | 2,990 | 10,000 |

All three have ledger transactions (credits actually burned). Gateway usage confirms metering: `service_slug=qwen`, billable, 70k+ input tokens on the agent path.

Note: only the curl charge is visible in `/usage/breakdown`; the two agent-path charges are invisible there — same **usage/actions join-key bug** (tenant-supplied `call_id` vs `logical_call_id`, tracked open since 063). Display bug only; metering and settlement verified intact above.

## Ops hygiene

- CP DB ipAllowList opened temporarily for the rated-charges query, reverted to empty and verified.
- Qwen key lives only in the gateway key pool + Fly machine env; repo scans clean.
- Machine states restored per snapshot (`nave-my-luna-2` left stopped).
- Housekeeping: `vaselin-test-agent-4` (`3463a828`) created by the image test-agent step remains; same cleanup question as 063's test agents.
