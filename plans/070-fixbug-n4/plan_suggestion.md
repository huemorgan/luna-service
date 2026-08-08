# Plan 070 — Fix bug N4: MCP inputSchema validation broken (mcp SDK 2.0.0 rename)

Execution follows the devprocess skill (`skills/devprocess/SKILL.md`): branch
`070-fixbug-n4`, E2E scenarios in `tests/070-fixbug-n4/` written before
implementation, phase-by-phase commits, and an `execution-summary.md` in this
folder when done.

## Problem

MCP server enable is completely broken in production. The `mcp` Python SDK
2.0.0 (published 2026-07-28) renamed all Python attributes from camelCase to
snake_case (`inputSchema` → `input_schema`, `isError` → `is_error`). The
unbounded dependency pin `mcp>=1.27.1` in `luna/pyproject.toml:37` allowed
2.0.0 in. The MCP client code in `luna-marketplaces` still reads the old 1.x
camelCase names, so every MCP server enable hits `AttributeError` — no MCP
tools register for any agent.

Secondary: `result.isError` (line 184) crashes every MCP tool call.

Silent security bug: `destructiveHint`/`readOnlyHint` getattr on lines 147/152
returns `False` default instead of the real SDK value, downgrading destructive
tools from `prompt_always` to `auto_approve`.

## Root Cause

SDK breaking rename in mcp 2.0.0 + unbounded dependency pin letting it in.

## Affected Files

1. `luna-marketplaces/marketplace-src/plugin_mcp/client.py` — lines 147, 152, 160, 184
2. `luna/pyproject.toml` — line 37 (unbounded mcp pin)
3. `luna/uv.lock` — lines 1282-1317 (locked mcp==2.0.0 + mcp-types==2.0.0)

## Proposed Fix

### Phase 1: Fix attribute access in client.py

**File: `luna-marketplaces/marketplace-src/plugin_mcp/client.py`**

1. **Line 160** — `t.inputSchema` → dual-read with fallback:
   ```python
   input_schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {"type": "object", "properties": {}}
   ```

2. **Lines 147/152** — annotation hints, dual-read with correct defaults:
   ```python
   # Line 147 (destructive hint):
   destructive = getattr(t.annotations, "destructive_hint", None)
   if destructive is None:
       destructive = getattr(t.annotations, "destructiveHint", False)

   # Line 152 (read-only hint):
   read_only = getattr(t.annotations, "read_only_hint", None)
   if read_only is None:
       read_only = getattr(t.annotations, "readOnlyHint", False)
   ```

3. **Line 184** — `result.isError` → dual-read:
   ```python
   is_error = getattr(result, "is_error", None) or getattr(result, "isError", False)
   ```

### Phase 2: Pin the dependency

**File: `luna/pyproject.toml` line 37**

Change: `mcp>=1.27.1` → `mcp>=2.0.0,<3`

Since 2.0.0 is already deployed and locked, accept it as the new floor. Then
run `uv lock` to regenerate the lockfile.

### Phase 3: Add regression test

Add a unit test using real `mcp_types.Tool` objects through the
`list_tools()` normalization path, asserting that `input_schema`,
`destructive_hint`, `read_only_hint`, and `is_error` are all correctly read.
This ensures future SDK renames break CI before they break production.

## Verification Steps

1. After applying Phase 1: enable an MCP server on a test agent — tools should
   register successfully (check `plugin_mcp_tools` rows are created).
2. Call an MCP tool — confirm no `AttributeError` on `isError`, confirm
   `is_error` is read correctly.
3. Enable an MCP server that exposes a destructive tool — verify the tool gets
   `prompt_always` approval mode, not `auto_approve`.
4. After Phase 2: run `uv lock` and confirm `mcp>=2.0.0,<3` resolves cleanly.
5. After Phase 3: run the new test, then temporarily break an attribute name
   to confirm the test catches it.

## Rollback Plan

**Option A — Dependency-only (fastest):**
Cap `mcp>=1.27.1,<2.0` in pyproject.toml, re-lock with `uv lock`, rebuild
image. This restores the 1.x camelCase attributes the current code expects.

**Option B — Code rollback:**
`git revert` the fix commit. The dual-name getattr pattern is inert on 1.x so
revert is safe on either SDK major. No data migration needed —
`plugin_mcp_tools` rows regenerate on every enable/refresh.

## Notes

- The dual-read getattr pattern (try 2.x name, fall back to 1.x) is
  intentionally defensive so the code works on both SDK majors during any
  transition window.
- No data migration is needed — MCP tool rows are ephemeral and regenerated on
  each server enable/refresh.
