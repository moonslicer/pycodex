# AI System Map

This document maps current architecture ownership and behavior contracts for pycodex.

## Purpose

- Keep module boundaries explicit.
- Point contributors to the right source of truth before making changes.
- Preserve runtime contracts that must stay stable across refactors.

## Sources of Truth

- Runtime architecture and status: `engineering-plan.md`
- Concise architecture snapshot: `summary-plan.md`
- Repo workflow and quality gates: `AGENTS.md`
- Harness process and scenario expectations: `docs/ai/harness.md`
- Durable architecture decisions: `docs/ai/memory.md`
- Historical milestone artifacts: `docs/archive/`

## Ownership Map (Current)

- CLI/runtime wiring and mode dispatch: `pycodex/__main__.py`
- Agent loop and turn orchestration: `pycodex/core/agent.py`
- Session state and history normalization: `pycodex/core/session.py`
- Initial context and project instruction loading: `pycodex/core/{initial_context,project_doc}.py`
- Model transport and streaming/complete APIs: `pycodex/core/model_client.py`
- Deterministic offline model path: `pycodex/core/fake_model_client.py`
- Compaction strategies and orchestration: `pycodex/core/compaction.py`
- Internal-agent event to protocol mapping: `pycodex/core/event_adapter.py`
- TUI JSON-RPC bridge and approval request flow: `pycodex/core/tui_bridge.py`
- Rollout schema, recording, replay, and session listing/resume helpers:
  - `pycodex/core/rollout_schema.py`
  - `pycodex/core/rollout_recorder.py`
  - `pycodex/core/rollout_replay.py`
  - `pycodex/core/session_store.py`
- Tool contracts, registry/router, and handlers:
  - `pycodex/tools/base.py`
  - `pycodex/tools/orchestrator.py`
  - `pycodex/tools/{shell,read_file,write_file,list_dir,grep_files}.py`
- Approval/sandbox primitives:
  - `pycodex/approval/policy.py`
  - `pycodex/approval/exec_policy.py`
  - `pycodex/approval/sandbox.py`
- Protocol event schemas: `pycodex/protocol/events.py`

## Key Runtime Contracts (Current)

- Mutating tools are gated in `execute_with_approval()` using `tool.is_mutating(args)`.
- `ToolAborted` is terminal for the active turn; `DENIED` is non-terminal structured output.
- Approval state is persisted only through `ApprovalStore` (`APPROVED_FOR_SESSION` cache entries).
- `shell` approval keys use canonicalized command + timeout; `write_file` uses resolved absolute path.
- `Session.to_prompt()` normalizes missing tool outputs and returns detached copies.
- Compaction uses stable marker `[compaction.summary.v1]` and applies boundary-aware range replacement.
- Rollout replay applies `compaction.applied` range mutations and preserves `display_history` for hydration.
- `--json` and `--tui-mode` payloads are emitted from typed models in `pycodex/protocol/events.py`.
- `TuiBridge` handles `user.input`, `approval.response`, `session.resume`, `session.new`, and `interrupt`.

## Update Criteria

Update this map when any of the following change:
- Module ownership or runtime boundaries.
- Public schemas/events/decision contracts.
- TUI bridge command/event surface.
- Rollout persistence/replay semantics.
