# pycodex/tools — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## ToolHandler Protocol
- Every tool must implement the `ToolHandler` protocol in `base.py` exactly — no duck typing shortcuts.
- `tool_spec()` must return a valid JSON schema dict that the OpenAI API accepts.
- `is_mutating()` must be correct: false positives (over-cautious) are acceptable; false negatives (claiming read-only when mutating) are bugs.

## Error Handling
- Tool errors are returned as strings with an `[ERROR]` prefix — never raised as exceptions to the agent loop.
- A tool that fails must still return a string result so the agent can reason about the failure.
- Timeouts must be caught and returned as `[ERROR] Command timed out after {n}s`.

## File Organization
- Each tool lives in its own file (`shell.py`, `read_file.py`, etc.).
- Never add a new tool to an existing tool file — always create a new file.
- Register new tools in `base.py`'s `ToolRegistry` — not in individual tool files.

## Concurrency
- Read-only tools (`read_file`, `list_dir`, `grep_files`) are safe to run concurrently.
- Mutating tools (`write_file`, `shell` with side effects) must not run concurrently against the same resource.
- The orchestrator enforces this — tools themselves do not need to manage concurrency.
