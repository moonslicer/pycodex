# PyCodex Architecture Summary

Last updated: 2026-03-07

## Current State

pycodex has moved from milestone planning to a working multi-mode runtime with these implemented layers:
- Async agent loop with model sampling + tool dispatch.
- Approval and sandbox enforcement for mutating tool calls.
- Context compaction with boundary-aware replacement (`[compaction.summary.v1]`).
- JSONL rollout persistence, replay, resume, and session file operations.
- JSON protocol mode (`--json`) and JSON-RPC TUI bridge mode (`--tui-mode`).

## Runtime Flow

```text
CLI mode selection
  -> config/profile resolution
  -> session build (new or replayed)
  -> model client + tool router wiring
  -> run loop (plain text, JSONL events, or TUI bridge)
```

Turn loop (`core/agent.py`):
1. Inject initial context and persist rollout metadata.
2. Optionally compact history.
3. Stream model output.
4. Dispatch tool calls and append tool outputs.
5. Record usage, emit completion events, flush rollout.

## Key Modules

- Core: `pycodex/core/{agent,session,model_client,compaction,event_adapter,tui_bridge}.py`
- Persistence: `pycodex/core/{rollout_schema,rollout_recorder,rollout_replay,session_store}.py`
- Tools: `pycodex/tools/{base,orchestrator,shell,read_file,write_file,list_dir,grep_files}.py`
- Approval/sandbox: `pycodex/approval/{policy,exec_policy,sandbox}.py`
- Protocol: `pycodex/protocol/events.py`
- Entrypoint: `pycodex/__main__.py`

## Locked Contracts

- `ToolAborted` remains terminal control flow for the active turn.
- `ReviewDecision.DENIED` remains non-terminal structured tool error output.
- `ApprovalStore` only persists `APPROVED_FOR_SESSION` decisions.
- Compaction marker string `[compaction.summary.v1]` must not change.
- Rollout replay must apply `compaction.applied` range mutations.
- Rollout replay error codes remain stable: `rollout_not_found`, `schema_version_mismatch`, `replay_failure`.

## Known Gaps

- `UNLESS_TRUSTED` currently behaves like `ON_REQUEST`.
- `ON_FAILURE` sandbox retry detection still uses non-zero exit-code approximation.
- Compaction strategy trigger still uses char-estimated prompt size; API usage is captured but not yet used as the primary trigger.

## Documentation Sources

- Detailed architecture and contracts: `engineering-plan.md`
- AI ownership map: `docs/ai/system-map.md`
- Harness and behavior validation guide: `docs/ai/harness.md`
- Durable architecture decisions: `docs/ai/memory.md`
- Historical milestone plans/reviews: `docs/archive/`

## Near-Term Plan

1. Promote API token usage to first-class compaction trigger input.
2. Add explicit trust bootstrap semantics for `UNLESS_TRUSTED`.
3. Improve sandbox-denial classification fidelity for `ON_FAILURE`.
4. Keep protocol parity checks between Python and TUI type definitions in every contract change.
