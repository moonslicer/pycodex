# PyCodex Engineering Plan (Current Architecture)

Last updated: 2026-03-07

## Purpose

This document is now the source of truth for pycodex runtime architecture and current delivery status.
It replaces the previous milestone planning text that described work as future changes.

Use this document to:
- understand how the current runtime is wired,
- preserve locked behavior contracts,
- decide what to build next without re-planning completed layers.

## Status Snapshot

Implemented and in daily use:
- Async model-tool agent loop with typed streaming events.
- Approval-gated tool execution with session-scoped approval caching.
- Optional command sandboxing (`danger-full-access`, `read-only`, `workspace-write`).
- Context compaction with boundary-aware replacement and model-generated summaries.
- Append-only JSONL rollout persistence, replay, resume, and session lifecycle commands.
- JSONL protocol mode (`--json`) and interactive bridge mode (`--tui-mode`) for TUI.
- Session commands: `session list`, `session read`, `session archive`, `session unarchive`.

Partially implemented or intentionally deferred:
- `ApprovalPolicy.UNLESS_TRUSTED` currently follows `ON_REQUEST` behavior (no trust bootstrap yet).
- `ON_FAILURE` sandbox retry treats any non-zero shell exit code as retry-eligible (approximation).
- `ThresholdV1Strategy` still triggers from char-estimated prompt tokens (API usage is captured in context but not used as the trigger signal yet).

## Runtime Modes

`pycodex/__main__.py` supports four operational paths:

1. Standard prompt mode
- `python -m pycodex "<prompt>"`
- Runs one turn and prints final assistant text.

2. JSON protocol mode
- `python -m pycodex --json "<prompt>"`
- Emits typed protocol events as JSONL to stdout.

3. TUI bridge mode
- `python -m pycodex --tui-mode`
- Reads JSON-RPC commands from stdin and emits protocol events to stdout.

4. Session command mode
- `python -m pycodex session <list|read|archive|unarchive> ...`
- Operates directly on rollout ledgers.

## Architecture Overview

```text
CLI (__main__.py)
  -> Config/profile resolution
  -> Session build (new or --resume replay)
  -> Model client (OpenAI or FakeModelClient)
  -> Tool router (registry + orchestrator)
  -> Execution mode:
     - run_turn() plain text
     - EventAdapter + run_turn() JSONL
     - TuiBridge.run() JSON-RPC loop

Agent (core/agent.py)
  -> ensure initial context
  -> persist session meta/history/turn records
  -> optional compaction pass
  -> model sampling loop (text deltas + tool calls)
  -> tool dispatch via router
  -> usage accounting + turn completion

Persistence
  -> RolloutRecorder writes append-only JSONL
  -> rollout_replay restores LLM-ready history + display history
  -> session_store handles listing and resume-path resolution
```

## Component Ownership

- Runtime entrypoint and mode dispatch: `pycodex/__main__.py`
- Agent loop and turn lifecycle: `pycodex/core/agent.py`
- Session state, history normalization, usage counters: `pycodex/core/session.py`
- Initial context assembly (policy + AGENTS docs + env): `pycodex/core/initial_context.py`
- Project doc loading from repo root to cwd: `pycodex/core/project_doc.py`
- Model streaming and completion adapter: `pycodex/core/model_client.py`
- Deterministic offline model path: `pycodex/core/fake_model_client.py`
- Compaction strategies/implementations/orchestration: `pycodex/core/compaction.py`
- Protocol event mapping and deterministic IDs: `pycodex/core/event_adapter.py`
- TUI JSON-RPC bridge and session switching: `pycodex/core/tui_bridge.py`
- Rollout schema contracts: `pycodex/core/rollout_schema.py`
- JSONL writer and path helpers: `pycodex/core/rollout_recorder.py`
- Replay/restore/import for rollouts: `pycodex/core/rollout_replay.py`
- Session listing and resume resolution helpers: `pycodex/core/session_store.py`
- Tool protocol, registry, routing, serialization: `pycodex/tools/base.py`, `pycodex/tools/outcome.py`
- Approval + sandbox orchestration: `pycodex/tools/orchestrator.py`
- Built-in tools: `pycodex/tools/{shell,read_file,write_file,list_dir,grep_files}.py`
- Approval key/value contracts and cache store: `pycodex/approval/policy.py`
- Deterministic shell exec classification: `pycodex/approval/exec_policy.py`
- Native sandbox argv adapters: `pycodex/approval/sandbox.py`
- JSONL event schemas consumed by CLI/TUI: `pycodex/protocol/events.py`

## Core Behavior Contracts (Locked)

Agent and turn semantics:
- `ToolAborted` is terminal for the active turn.
- `DENIED` is non-terminal and serialized back as structured tool error payload.
- Pending tool calls are closed with synthetic tool outputs (`"aborted by user"` / `"interrupted"`) on abort/cancel paths.

Session invariants:
- `Session` is the only owner of prompt-history mutation and usage counters.
- `Session.to_prompt()` returns detached copies and normalizes missing tool outputs.
- Tool result history content is capped (`MAX_TOOL_RESULT_CHARS`) to bound prompt growth.

Compaction invariants:
- Summary marker string `[compaction.summary.v1]` is the stable boundary token.
- `replace_range_with_system_summary()` is the canonical mutation path.
- Boundary-aware compaction preserves prior summary blocks and only replaces new eligible ranges.
- `model_summary_v1` is default implementation and falls back to `local_summary_v1` when no model `complete()` capability is present.

Approval and sandbox invariants:
- Approval state is persisted only through `ApprovalStore` (`APPROVED_FOR_SESSION` only).
- Shell approval key uses canonicalized command + timeout tuple.
- Write-file approval key is resolved absolute target path.
- Restrictive sandboxing is opt-in via policy; unavailable native adapter returns `sandbox_unavailable`.

Rollout/replay invariants:
- Rollout schema major version remains `1.x` (`SCHEMA_VERSION = "1.0"`).
- `compaction.applied` replay mutates history using `replace_start`/`replace_end`.
- Replay returns both transformed `history` and untransformed `display_history` for UI hydration.
- Stable replay error codes: `rollout_not_found`, `schema_version_mismatch`, `replay_failure`.

## Protocol and TUI Contracts

Protocol events currently modeled in `pycodex/protocol/events.py`:
- Thread/turn lifecycle: `thread.started`, `turn.started`, `turn.completed`, `turn.failed`.
- Item lifecycle: `item.started`, `item.updated`, `item.completed`.
- Context signals: `context.compacted`, `context.pressure`.
- Approval event: `approval.request`.
- Session UX events: `session.listed`, `session.status`, `session.hydrated`, `session.error`.
- Slash command UX events: `slash.unknown`, `slash.blocked`.

TUI bridge JSON-RPC methods currently handled:
- `user.input`
- `approval.response`
- `session.resume`
- `session.new`
- `interrupt`

Slash commands handled in TUI text input:
- `/status`
- `/resume`
- `/new`

## Configuration Surface (Current)

Key runtime config fields in `pycodex/core/config.py`:
- `model`, `api_key`, `api_base_url`, `cwd`
- `profile` (built-in or loaded from TOML)
- `project_doc_max_bytes`
- `compaction_threshold_ratio`
- `compaction_context_window_tokens`
- `compaction_strategy`
- `compaction_implementation`
- `compaction_custom_instructions`
- `compaction_options`
- `default_approval_policy`
- `default_sandbox_policy`

Primary env overrides:
- `PYCODEX_MODEL`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `PYCODEX_CWD`
- `PYCODEX_INSTRUCTIONS`
- `PYCODEX_COMPACTION_*`
- `PYCODEX_DEFAULT_APPROVAL_POLICY`
- `PYCODEX_DEFAULT_SANDBOX_POLICY`
- `PYCODEX_FAKE_MODEL`

## Test Coverage Map

High-signal suites for current architecture:
- Core agent/session/model/compaction/rollout/TUI: `tests/core/`
- Approval policy + sandbox behavior: `tests/approval/`, `tests/tools/test_orchestrator.py`
- Tool contracts and integration behavior: `tests/tools/`
- Protocol schemas and adapters: `tests/protocol/`, `tests/core/test_event_adapter.py`
- Harness behavior scenarios: `tests/agent_harness/`
- CLI end-to-end flows (including resume/session commands): `tests/e2e/`

## Historical Milestone Artifacts

Historic milestone plans and reviews are kept in `docs/archive/` for traceability.
There is no active `todo-m*.md` tracker in the repo root at this time.

## Next Engineering Priorities

1. Tighten compaction trigger to use API-reported usage as first-class signal.
2. Implement real trusted-command behavior for `UNLESS_TRUSTED`.
3. Improve sandbox-denial detection for `ON_FAILURE` retry prompts.
4. Add durability hardening around partial session metadata and recovery diagnostics.
5. Keep Python protocol models and TUI TypeScript protocol types in strict lockstep for every event contract change.
