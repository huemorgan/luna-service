# N4: MCP inputSchema Attribute Error — Fix Plan

## Bug Summary
MCP server tool registration fails for ALL agents with: `'Tool' object has no attribute 'inputSchema'`

Any MCP server that connects successfully fails during tools/list normalization in `plugin_mcp/client.py`.

## Root Cause
The MCP SDK's `Tool` Pydantic model uses snake_case for field names (`input_schema`), but the code at `client.py:160` accesses `t.inputSchema` (camelCase). The constructor accepts `inputSchema` as an alias for setting values, but attribute access requires the field name `input_schema`.

**Evidence**: `Tool.model_fields.keys()` returns `['name', 'title', 'description', 'input_schema', 'execution', 'output_schema', 'icons', 'annotations', 'meta']`

## Fix
**File**: `luna-marketplaces/marketplace-src/plugin_mcp/client.py`, line 160

**Before**:
```python
"input_schema": t.inputSchema or {"type": "object", "properties": {}},
```

**After**:
```python
"input_schema": t.input_schema or {"type": "object", "properties": {}},
```

Single character change: `inputSchema` → `input_schema` (the Pydantic field name, not the alias).

## Scope
- Only one occurrence of `.inputSchema` attribute access in the codebase
- `wrapper.py:55` already uses `tool.get("input_schema")` on dicts (correct)
- `manager.py:409` uses `t.get("input_schema")` on dicts (correct)
- No other files affected

## Risk
Very low — single attribute name fix, matches the SDK's own field name. No behavioral change other than fixing the AttributeError.

## Verification
After deploying: MCP servers should register tools successfully. The `inputSchema` fingerprint in error logs should disappear.
