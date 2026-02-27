# pycodex/tools — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## ToolHandler Protocol
- Every tool must implement the `ToolHandler` protocol in `base.py` exactly — no duck typing shortcuts.
- `tool_spec()` must return a valid JSON schema dict that the OpenAI API accepts.
- `is_mutating()` must be correct: false positives (over-cautious) are acceptable; false negatives (claiming read-only when mutating) are bugs.
- Tools may optionally expose `approval_key(args, cwd)` when default `{tool,args}` keys are not appropriate; key shape must be deterministic for semantically equivalent operations.

## Error Handling
- Tool handlers return a typed `ToolOutcome` (`ToolResult | ToolError`) — never raise exceptions to the agent loop.
- A tool that fails must return `ToolError(message=..., code=...)` so the agent can reason about the failure.
- Timeouts must be caught and returned as `ToolError(message="Command timed out after {n}ms", code="timeout")`.
- Serialization to JSON string happens at `ToolRegistry.dispatch` via `serialize_tool_outcome` — not inside individual tool handlers.
- `ToolAborted` is a control-flow exception raised by the orchestrator and must propagate through `ToolRegistry` so the agent can terminate the active turn.

## File Organization
- Each tool lives in its own file (`shell.py`, `read_file.py`, etc.).
- Never add a new tool to an existing tool file — always create a new file.
- Register runtime default tools in the CLI entrypoint wiring (`pycodex/__main__.py`), not inside individual tool files.

## Concurrency
- Current agent behavior dispatches tool calls sequentially.
- The orchestrator currently deduplicates concurrent prompts per approval key; it does not provide general resource-level execution locking for tool handlers.
- If tool-call parallelism is introduced later, add explicit tests for mutating-resource safety and approval prompt behavior.
