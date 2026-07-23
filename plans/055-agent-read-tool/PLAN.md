# 055 — Agent `read` tool: stop dumping whole docs into context

## Context

Today anything a Luna agent "reads" (plugin results, fetched docs, files)
lands **verbatim in the context window** as a tool result. The only defenses
are deterministic: the 48k-char single-result hard cap, the 24k-char per-turn
microcompact budget (older results stubbed on the wire), and Haiku-based
condense of old history (`luna/agent/context.py`). There is no way for the
agent to read a large source *incrementally* or *with a direction* — it gets
everything or a stub.

Roy (2026-07-23): reading should work like Claude Code's Read — agent-directed,
paged, not full dumps.

## Research — read strategies in shipping agents (2026-07-23)

Five distinct strategies exist; no major tool uses "summarize everything on
the way in":

1. **Paged verbatim read** — Claude Code `Read`: `offset`/`limit` params,
   2,000-line default cap, ~25k-token cap, `cat -n` line numbers, long lines
   truncated; guidance says "when you know which part you need, read only that
   part". Cursor `read_file` is the same shape with 250-line chunks; Gemini
   CLI `read_file` likewise. **No model in the loop** — deterministic, exact,
   prompt-cache-friendly. The "direction" lives in the agent loop, not the
   tool: grep/search first, then targeted read.
2. **Search-then-read** — Claude Code idiom (Grep/Glob → Read with offset);
   Cursor adds a semantic index (AST/~500-token chunks, custom embedding
   model; they report +12.5% agent accuracy). Relevance is located *before*
   any content enters context.
3. **Directed extraction via a small model** — Claude Code `WebFetch`: fetch →
   markdown → a small fast model answers a caller-supplied `prompt` against
   the content; only the *answer* enters the main context. This is the
   "summarize with a specific idea in mind" mode — it exists, but only for
   web content, and always with an explicit question, never blind
   summarization.
4. **Delegated reader subagent** — Claude Code Explore/Task agents: question
   in, distilled findings out; the raw text is read in a *separate* context
   that is thrown away. Agentic RAG.
5. **Structural map** — Aider repo map: tree-sitter symbol graph +
   personalized PageRank rendered under a token budget. Codebase-specific;
   not applicable to general docs.

Key insight: Claude Code's Read is **not** a summarizer. Default is verbatim
fidelity (exact wording survives); lossy extraction (3)/(4) is opt-in via
separate tools. Luna's own system-prompt recall rules already encode why:
paraphrases of the record are not the record.

## Proposal

Copy the Claude Code split: verbatim+paged by default, directed extraction as
an explicit mode.

### Phase 01 — `read` tool (paged, verbatim)

- New core tool `read(source, offset=0, limit=None)` over the agent's
  readable sources:
  - workspace/skill files (path),
  - **oversized tool results** by stub id — microcompact/hard-cap stubs
    already point at the full DB row; today the only retrieval is
    `recall_conversation` (all-or-nothing). `read` pages through them.
- Caps per call: ~1,600 lines / ~24k chars (aligns with
  `TOOL_RESULT_KEEP_BUDGET_CHARS`); `cat -n` line numbers; long lines
  truncated; footer `[... N more lines — read(source, offset=X)]`.
- System-prompt guidance: "read only the part you need; page, don't re-read".

### Phase 02 — directed extraction (`query` mode)

- `read(source, query="...")` → `utility_complete` (existing `summarization`
  chain → Haiku, cost-tracked) returns the answer **plus exact quoted spans
  with line refs**, WebFetch-style. Raw doc never enters the main window.
- Explicitly NOT auto-summarize: no query → no model call.

### Phase 03 — document handles (flip the default)

- Plugins returning large payloads can return a **document handle**: payload
  goes to the doc store, context receives `{handle, size, head preview}`;
  agent pages or queries it via `read`. Per-plugin opt-in flag first (Gmail
  fetch, web fetch, playbook status are the known offenders — the 1.86M-char
  incident in 041/phase01).

### Phase 04 — reader subagent ("go find X")

- A delegated reader loop: takes a question, reads/pages/greps sources in its
  OWN throwaway context (restricted tool registry: `read` + search only),
  returns answer + citations; raw text never touches the main window.
- Escalation ladder: page it yourself (01) → single-doc Haiku query (02) →
  reader subagent for multi-doc / multi-step questions (04).
- Requires a second isolated reasoning loop in the runtime (own context,
  budget/billing attribution, kill switch) — new primitive, reusable later
  for research/playbook delegation. Ship 01/02 first; do not block on this.

### Later / maybe

- Semantic index over the doc store (Cursor-style embedding chunks) — only if
  query-mode extraction proves too slow/costly on big docs.

## Status

- [x] Research (2026-07-23)
- [ ] Roy review of proposal
- [ ] Phase 01 implementation + tests
- [ ] Phase 02 query mode
- [ ] Phase 03 plugin handles
- [ ] Phase 04 reader subagent (needs runtime subagent primitive)
