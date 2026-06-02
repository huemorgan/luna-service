# Luna Service Dojo — Vision

## What This Is

The Luna Service Dojo is the LLM-driven testing environment for the **multi-tenant hosting platform** (this repo). It complements — but does NOT replace — Luna's own dojo (`luna/dojo/`) which tests the agent itself.

| Project Dojo | What It Tests |
|--------------|---------------|
| `luna/dojo/` (the OSS agent) | Does Luna's agent behave correctly? Conversations, tools, approvals, memory, plugins. |
| `luna-service/dojo/` (this) | Does the **platform** work? Signup, provisioning, isolation, routing, billing, lifecycle. |

When you test `luna-service`, you're not asking "is Luna a good agent?" — you're asking "when 50 different users sign up, do they each get their own working Luna that's truly isolated from the others?"

## The Core Idea

The platform's correctness lives in flows that span the entire system: a browser, an OAuth provider, a control plane, a Fly Machine boot, a Postgres schema creation, a router proxy, and finally Luna's SSE stream coming back to the user. **None of this can be verified by unit tests.** It requires driving a real browser through a real signup flow and observing whether the right Luna shows up.

So — just like Luna's dojo — the test framework is **you**: an LLM agent in Cursor that opens a browser, performs the steps, and judges what happened.

What this catches that coded tests miss:
- A signup flow that "technically works" but redirects to the wrong URL
- A Luna that boots but with the previous user's vault key (catastrophic isolation bug)
- A routing layer that proxies to the right Luna 95% of the time but sometimes cross-routes
- A provisioning UX that takes 90 seconds with no progress indicator (technically passes, real users bail)
- A "your Luna is ready" page that appears before Luna is actually ready

## Structure

```
luna-service/
├── plans/                      # Implementation phases (PLAN.md per phase)
│   ├── 001-luna-hosted-mode/
│   ├── 002-control-plane-skeleton/
│   ├── 003-local-provisioning-and-routing/
│   └── 004-fly-deployment/
├── tests/                      # Per-phase test scenarios (mirror of plans/)
│   ├── 001-luna-hosted-mode/
│   ├── 002-control-plane-skeleton/
│   ├── 003-local-provisioning-and-routing/
│   └── 004-fly-deployment/
├── dojo-vision/                # This document
├── dojo-results/               # Numbered test run results with screenshots
│   └── 0001-001-luna-hosted-mode/
└── skills/devprocess/          # Standard dev process the LLM follows
```

## How Tests Work

Each test scenario is a `.md` file structured as:

1. **Preconditions** — what state needs to exist before the scenario can start (clean DB? specific user? specific OAuth setup?)
2. **Scenario** — step-by-step what to do (open browser, click, type, wait for X)
3. **Expected behavior** — described in human terms (not regex/assertions)
4. **Fail conditions** — specific anti-patterns that indicate a regression
5. **Verify** — what to look at in DB, logs, or UI to confirm correctness

The LLM (you) opens the browser, follows the script, screenshots at each meaningful step, reads the DOM, queries the DB if needed, and judges pass/fail with evidence.

## What Makes Platform Testing Different from Agent Testing

Some unique concerns for platform tests:

**Multi-user scenarios are first-class.** A typical test isn't "what happens when I sign up" — it's "what happens when User A signs up, then User B signs up, then User A logs back in and queries their memory? Does User A's memory survive? Does User A see any of User B's data?"

**Time matters.** The platform has provisioning latency, cold start latency, suspension behavior. Scenarios test for "does this complete within X seconds" not just "does it complete."

**State spans many systems.** A bug in isolation might involve Postgres roles + R2 prefix scoping + Fly Machine env vars all interacting. Scenarios need to verify state across all of these, not just "the UI looks right."

**Failure modes are critical.** What happens when Fly is down during signup? When the user's Machine fails to boot? When their Postgres schema creation succeeds but their Machine creation fails? Real platforms get these wrong; tests must exercise them.

## Running the Platform Locally

Local development uses the same control plane code but swaps out the runtime provider:

- **Production:** control plane provisions Fly Machines via Fly API
- **Local dev:** control plane provisions local Docker containers via Docker socket

This means dojo tests can run end-to-end on a developer's laptop without paying for Fly resources — same code paths, same architecture, same outcomes.

```bash
# Start the local stack
docker compose up -d        # Postgres + Redis for control plane + tenant DB
cd cloud && uv run uvicorn main:app --reload
# → http://localhost:8000 (control plane)
# Luna images built locally; Lunas spun up as local Docker containers
```

## Results

Every test run produces a numbered results folder:

```
dojo-results/
├── 0001-001-luna-hosted-mode/
│   ├── summary.md
│   ├── 01-trusted-header-accepted.md
│   ├── 02-untrusted-header-rejected.md
│   └── screenshots/
├── 0002-002-control-plane-skeleton/
│   ├── summary.md
│   └── ...
```

Each `summary.md`:

```markdown
# Test Run: 002-control-plane-skeleton
Date: 2026-06-15 14:30
luna-service commit: a3f7b2c
luna submodule: 74f4115
Environment: local

## Results
| # | Scenario | Result | Notes |
|---|----------|--------|-------|
| 01 | Google sign-in (new user) | PASS | Account auto-created; dashboard shown |
| 02 | Google sign-in (returning) | PASS | Lands on existing account |
| 03 | Sign out | PASS | Session cleared, redirected to landing |
| 04 | Multi-account user picker | FAIL | Picker shown but selecting doesn't update session |

## Regressions
- Scenario 04: AccountPicker.tsx onChange not wired

## Fixes Applied During Run
- (none — regressions filed for next iteration)
```

## What This Is NOT

- Not a CI/CD pipeline (those are coded tests, separately)
- Not a replacement for coded unit/integration tests (have those too)
- Not Luna's own dojo (different layer — that tests the agent)
- Not optional (devprocess mandates dojo walkthrough before reporting plan complete)

## Why "Dojo"

A dojo is a place for practice and mastery. Luna's dojo is where we practice verifying the agent's behavior; the Service Dojo is where we practice verifying the platform's behavior. Same philosophy, different scope.
