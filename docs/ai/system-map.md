# AI System Map

This document is the architecture map for agent behavior and contracts in this repo.

## Purpose
- Show where AI behavior is defined.
- Keep service boundaries and contracts explicit.
- Point contributors to the correct source of truth before implementation.

## Sources of Truth
- Policy and workflow rules: `AGENTS.md`
- Architecture and responsibilities: `engineering-plan.md`
- Milestone tracking and completion evidence: `todo-m5.md` (active), `archive/todo-m2.md`, `archive/todo-m3.md`, `archive/todo-m4.md` (archived)
- Evaluation and regression process: `docs/ai/harness.md`
- Durable decisions and postmortems: `docs/ai/memory.md`

## Contract-First Rules
- Define API and event contracts before implementation details.
- Capture acceptance criteria in the task/PR before coding non-trivial changes.
- Update this map when contract ownership moves.

## Ownership Map (Current)
- Core agent loop and turn orchestration: `pycodex/core/agent.py`
- Session and conversation state: `pycodex/core/session.py`
- Session listing and resume path resolution helpers: `pycodex/core/session_store.py`
- Model transport and streaming mapping: `pycodex/core/model_client.py`
- Internal-to-protocol event mapping and IDs: `pycodex/core/event_adapter.py`
- TUI mode JSON-RPC command bridge: `pycodex/core/tui_bridge.py`
- Runtime configuration loading: `pycodex/core/config.py`
- Deterministic no-network model for local testing: `pycodex/core/fake_model_client.py`
- Protocol event schemas and JSONL contracts: `pycodex/protocol/events.py`
- Tool contracts, dispatch, and serialization boundary: `pycodex/tools/base.py`
- Approval flow and prompt orchestration: `pycodex/tools/orchestrator.py`
- Approval policy and session-scoped cache store: `pycodex/approval/policy.py`
- Tool handlers in current production surface:
  - `pycodex/tools/shell.py`
  - `pycodex/tools/read_file.py`
  - `pycodex/tools/write_file.py`
  - `pycodex/tools/list_dir.py`
  - `pycodex/tools/grep_files.py`

## Key Runtime Contracts (Current)
- Mutating tool calls are gated in `execute_with_approval()` based on `tool.is_mutating(args)`.
- Approval decisions are stateful only through `ApprovalStore`; only `APPROVED_FOR_SESSION` is cached.
- `DENIED` returns `ToolError(code="denied")` and does not raise.
- `ABORT` raises `ToolAborted`; this propagates through `ToolRegistry` and is treated as terminal turn control flow by `core/agent.py`.
- `write_file` approval key is the resolved absolute target path.
- `shell` approval key is canonicalized conservatively:
  - normalizes equivalent wrapper forms (`/bin/bash -lc` vs `bash -lc`)
  - normalizes whitespace only for a strict safe token subset
  - preserves semantically sensitive inline shell forms as distinct keys
- Tool handlers return typed outcomes (`ToolResult | ToolError`); JSON serialization happens in `ToolRegistry.dispatch()`.
- In `--json` and `--tui-mode`, protocol payloads are emitted from typed models in `pycodex/protocol/events.py`.
- `pycodex/core/tui_bridge.py` accepts `user.input`, `approval.response`, and `interrupt` JSON-RPC methods; unknown or malformed input is ignored safely.
- `pycodex/__main__.py` is the entrypoint contract boundary for CLI args, runtime wiring, and top-level error handling.

## Update Criteria
Update this file when any of the following change:
- A new service boundary or module ownership is introduced.
- A contract/schema is added or modified.
- A harness surface is added/removed.
