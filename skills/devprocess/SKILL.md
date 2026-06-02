---
name: devprocess
description: Standard dev process for executing plans — branch, test, build, verify
---

# Dev Process

## ⛔ CRITICAL — DATA PRESERVATION

**NEVER delete, drop, or destroy production data. EVER.**

When writing migrations, schema changes, or any code that touches existing data:
- **ALWAYS migrate and preserve existing data** — find a way to transform, move, or archive it.
- **NEVER use `DROP TABLE`, `DELETE FROM`, or `DROP COLUMN`** on tables/columns that contain production data without first copying that data to its new home **and verifying the copy succeeded**.
- If merging tables, ensure **zero rows are silently skipped** — handle conflicts explicitly (update, merge, log), not with `ON CONFLICT DO NOTHING` + DROP.
- If renaming or restructuring, keep the old column/table until the migration is verified in production.
- **When in doubt, keep the data.** Storage is cheap. Lost data is irreplaceable.

This rule is non-negotiable. Violating it is a production incident.

---

Follow these steps when executing a plan from `plans/XXX-name/PLAN.md`:

## 1. Branch

Create (or switch to) a branch matching the plan folder name:
```
git checkout -b XXX-name
```
If the branch already exists, switch to it. The branch name, plan folder,
and test folder should all share the same name.

## 2. Write E2E Test Scenarios First

Create `tests/XXX-name/` with **scenario files** (`.md` or `.yaml`) **before**
writing implementation. These are NOT coded assertion tests — they are
instructions for YOU (the LLM agent) to follow in a real browser.

Each scenario describes:
- What to do (navigate, click, type, wait)
- What to look for (DOM state, visual layout, text content, behavior)
- What counts as pass/fail

**E2E in this project means: you open a browser, perform the actions, and
judge the result with your own eyes (screenshots + DOM reading).** You are
the test runner. You are the assertion engine. No `expect()` calls — you
read the HTML, take screenshots, observe what happened, and decide if it
matches the intended behavior.

Why: Coded assertions only catch what you remembered to assert. An LLM
reading the full page state catches unexpected regressions, broken layouts,
wrong copy, missing elements, and behavioral issues that no one wrote a
matcher for.

### How to execute E2E scenarios

1. Open the app in the browser (use browser MCP tools)
2. Follow the scenario steps
3. After each meaningful action: take a screenshot AND read the DOM/snapshot
4. Compare what you see against the scenario's expected outcome
5. Record pass/fail with evidence (screenshot path or DOM excerpt)
6. If something is wrong — fix it, re-run the scenario

## 3. Execute the Plan

Implement the plan phase by phase. After each phase:
- Build (`npm --prefix client run build`) — must pass
- Check lints on edited files — fix any new errors
- Commit the phase

## 4. Run E2E Scenarios

Start the dev server, then execute each scenario from `tests/XXX-name/`:

1. Open the browser using MCP browser tools
2. Walk through each scenario file step by step
3. For every step: **screenshot + DOM snapshot** — read what's on screen
4. Judge pass/fail yourself based on what you observe
5. Fix anything broken. Re-run the scenario until you're satisfied.

**You are the test framework.** There is no `npx playwright test` to run.
You drive the browser, you see the result, you decide if it works.

## 5. Live Walkthrough (MANDATORY — do not skip)

Coded tests passing is not enough. Before reporting the plan
complete, follow the **agent-live-walkthrough** skill: drive the
running UI through a real multi-turn conversation in a browser,
observe the agent's replies, and judge them qualitatively. Fix any
regressions you find before reporting.

This step exists because coded tests test what you remembered to
assert; the walkthrough tests what you forgot. If you skip it, the
user catches the bugs in their first conversation — which has
happened and is the reason this step is in the dev process.

### 5a. The "first user query" check

Before opening the browser, write down — explicitly — the single
most likely thing the user will type to verify what you built. Then
type that, exactly, before reporting done.

If the plan touched the agent runtime, prompts, tools, or any
cross-cutting infrastructure (gates / middlewares / engines /
registries that every existing consumer is supposed to flow
through), the "first user query" is almost never your test fixture
— it's whatever existing capability the user happens to use today
that *should* now route through the new piece. Examples:
- Shipped an approval engine? The first user query is "delete
  something destructive". If your tests only cover `memory_forget`
  and you didn't verify Monday's `delete_board` actually routes
  through, you have shipped a half-engine.
- Shipped a rate limiter? The first user query is "burst-call
  some existing tool 50 times in a row". Not your synthetic
  fixture tool.
- Shipped a redactor / masker? The first user query is "show me
  any secret value through the chat", using a real plugin's
  output, not a string you crafted.

The shape of the failure that this prevents: the engine works in
isolation, all tests pass, but the integration with EXISTING
consumers was never wired (defaults left wrong, registration
missing, policy not propagated, tool description ignored). The
user's first turn exposes it instantly because they don't know to
use your fixture — they use the real tools.

So: enumerate the existing consumer categories the new piece
should cover, and exercise at least one tool from each in the
walkthrough. If you find a gap, the fix usually lives in the
wrapper / registration site, not in the engine itself.

## 6. Report

Only after both E2E scenarios AND the live walkthrough pass, report to
the user with:
- Summary of what was built
- E2E scenario results (per-scenario pass/fail with screenshot evidence)
- Live walkthrough results (per-scenario pass/fail + any fixes
  applied during the walkthrough)
- Any issues found and fixed
