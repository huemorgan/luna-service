# AGENTS.md

Project rules for the LLM working on luna-service. Read once per session.

## Communication

**🚫 NEVER use the `AskQuestion` tool / multiple-choice popups. EVER.** No exceptions. Ask any follow-up as plain prose in the chat. The user has asked for this many times — a popup is a hard failure.

**Be ruthlessly succinct.** Default to the fewest words that answer the question. No multi-section essays, no tables, no "let me explain the tradeoffs" unless explicitly asked. Even for design/architecture questions: give the recommendation + the one key reason, then stop. If the user wants depth they will ask. Long replies are a failure mode here — the user has called this out repeatedly.

**Match answer length to question depth.** The user reads everything.

**Answer first, details second.** Lead with the bottom line — the number, the yes/no, the recommendation. Supporting detail comes after, and only if it adds value. If the user asks "how long?" the first line must be the time, not a table of steps.

Defaults:
- Short question → 1-3 sentences. Not paragraphs.
- Medium question → answer + one short justification. No "summary" at the end.
- Long task → do the work, report the result, stop. The diff speaks for itself.

Cut these reflexively:
- Preambles. "Let me first check…", "I'll now…", "Great question!". Just do the thing.
- Closing summaries when the work is already shown above. No "Done! Here's what I changed…" recap of a diff you just made.
- Tables for 2 items. Use prose.
- Headers for 1-section answers.
- Multiple ways to say the same thing.
- Emojis. None unless asked.
- Restating the question back before answering.

Keep:
- The actual answer.
- One critical reason or caveat when the choice matters.
- Code blocks (with the project's required `startLine:endLine:filepath` format for citations).
- A single follow-up question when blocked. Don't list options if the answer is obvious.

When asked a question: **answer it.** Don't write code unless asked to build/fix/change.

When making a decision the user might want to revisit: state the choice + one line on why, not a comparison matrix.

When something goes wrong or you're uncertain: say so plainly. Don't pad.

## Project structure pointers

- `vision/vision.md` — product positioning, billing model, auth, scope
- `vision/filesystem-architecture.md` — why Postgres + R2 + Volumes
- `plans/README.md` — MVP phase overview + decisions punted
- `plans/00X-*/PLAN.md` — per-phase implementation plan
- `tests/00X-*/` — dojo-style E2E scenarios for that phase (LLM is the test runner)
- `dojo-vision/vision.md` — testing philosophy for the platform
- `skills/devprocess/SKILL.md` — branch / write tests first / implement / walkthrough / report
- `.env.example` — every env var + where to source it from
- `luna/` — git submodule, the OSS agent (don't edit lightly, has its own roadmap)

## Existing infra (don't recreate)

- Render account exists. New `luna-service` web service created (separate from old `runluna`)
- Cloudflare `luna.com.ai` zone exists — user will move domain to `luna-service.onrender.com` when ready
- LLM keys live in `../luna/.env` (Anthropic, OpenAI, Tavily) and also in Render dashboard
- Fly account: user opening — needed only for phase 004
- Google OAuth client: not yet created, lives under `novalystrix.ai` Workspace

## Hard rules

- **Never** commit `.env` or any real secret
- **Never** destroy data without a verified backup (see `skills/devprocess/SKILL.md` data-preservation section)
- **NEVER write ANY file inside `luna/`** — not code, not plans, not docs, not tests. The submodule is READ-ONLY from this repo, no exceptions, "it's just a markdown file" included. Proposals for Luna work go in `plans/luna-proposals/` in THIS repo. Actual Luna changes happen only when the user explicitly says to work on the Luna project, via `skills/luna-submodule-changes/SKILL.md`
- **Never** modify or renumber past plans that were already executed (`plans/00X-*`). Executed plans are historical records — new work gets a new plan
- **Always** follow the devprocess skill when executing a plan — branch, scenarios first, implement, browser walkthrough, report
- **Always** prefer reusing existing infra (Render slot, Cloudflare zone) over creating parallel resources
