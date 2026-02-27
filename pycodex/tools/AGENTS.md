# pycodex/tools — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## ToolHandler Protocol
- Every tool must implement the `ToolHandler` protocol in `base.py` exactly — no duck typing shortcuts.
- `tool_spec()` must return a valid JSON schema dict that the OpenAI API accepts.
- `is_mutating()` must be correct: false positives (over-cautious) are acceptable; false negatives (claiming read-only when mutating) are bugs.

## Error Handling
- Tool handlers return a typed `ToolOutcome` (`ToolResult | ToolError`) — never raise exceptions to the agent loop.
- A tool that fails must return `ToolError(message=..., code=...)` so the agent can reason about the failure.
- Timeouts must be caught and returned as `ToolError(message="Command timed out after {n}ms", code="timeout")`.
- Serialization to JSON string happens at `ToolRegistry.dispatch` via `serialize_tool_outcome` — not inside individual tool handlers.

## File Organization
- Each tool lives in its own file (`shell.py`, `read_file.py`, etc.).
- Never add a new tool to an existing tool file — always create a new file.
- Register new tools in `base.py`'s `ToolRegistry` — not in individual tool files.

## Concurrency
- Read-only tools (`read_file`, `list_dir`, `grep_files`) are safe to run concurrently.
- Mutating tools (`write_file`, `shell` with side effects) must not run concurrently against the same resource.
- The orchestrator enforces this — tools themselves do not need to manage concurrency.
