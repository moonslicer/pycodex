# PyCodex: Reimplementing Codex Core in Python

## Context

OpenAI's Codex CLI is a sophisticated AI coding agent built in Rust + TypeScript. By reimplementing its core in Python, you'll deeply understand:
- How agent loops work (prompt → model → tool calls → feedback loop)
- Tool registration, dispatch, and concurrent execution patterns
- Permission/approval systems with session-scoped caching
- Sandboxing strategies for safe command execution
- Event-driven streaming architecture
- Terminal UI for interactive agent sessions

The Python version will be called **pycodex** — a from-scratch reimplementation using idiomatic Python, not a port.

---

## Project Structure

```
pycodex/
├── pyproject.toml
├── pycodex/
│   ├── __init__.py
│   ├── __main__.py                # Entry point: python -m pycodex
│   │
│   ├── core/                      # Agent engine
│   │   ├── __init__.py
│   │   ├── agent.py               # Main agent loop (≈ codex.rs::run_turn)
│   │   ├── session.py             # Session state & message history
│   │   ├── model_client.py        # Model API abstraction (streaming)
│   │   └── config.py              # Config loading (env + TOML)
│   │
│   ├── tools/                     # Tool system
│   │   ├── __init__.py
│   │   ├── base.py                # ToolHandler protocol, Registry, Router
│   │   ├── orchestrator.py        # Approval → sandbox → execute → retry
│   │   ├── shell.py               # Shell command execution
│   │   ├── read_file.py           # File reading with line numbers
│   │   ├── write_file.py          # File writing / patch application
│   │   ├── list_dir.py            # Directory listing
│   │   └── grep_files.py          # File content search
│   │
│   ├── approval/                  # Permission system
│   │   ├── __init__.py
│   │   ├── policy.py              # Approval levels, decisions, store
│   │   ├── exec_policy.py         # Command prefix allow/deny rules
│   │   └── sandbox.py             # Sandbox policies & enforcement
│   │
│   ├── protocol/                  # Event protocol
│   │   ├── __init__.py
│   │   └── events.py              # ThreadEvent, ThreadItem types
│   │
│   └── cli/                       # User interface
│       ├── __init__.py
│       ├── app.py                 # CLI entry point (typer)
│       ├── tui.py                 # Interactive terminal UI (textual)
│       └── display.py             # Rich markdown/code rendering
```

## Dependencies

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "openai>=1.0",       # Model API (Responses API with streaming)
    "pydantic>=2.0",     # Data validation, event serialization
    "rich>=13.0",        # Terminal formatting, markdown, syntax highlight
    "textual>=0.40",     # TUI framework (built on rich)
    "typer>=0.9",        # CLI argument parsing
    "tiktoken>=0.5",     # Token counting
]
```

---

## Build-Up Plan: 6 Incremental Milestones

Each milestone produces a **runnable system**. You can stop at any milestone and have something useful.

---

### Milestone 1: Minimal Agent Loop (Non-Interactive) ✅ COMPLETE

**Goal**: A CLI that takes a prompt, calls a model, executes tool calls, loops until done, and prints the result.

**Status**: **Complete** — all tasks (T1–T9, T8.5) implemented and passing. No open items.

---

#### What was built

All 8 planned files were created with the following implementations and notable divergences from the original spec:

1. **`core/config.py`** ✅ — `Config` (Pydantic BaseModel) with `model`, `api_key`, `api_base_url`, `cwd`. `load_config()` merges defaults < TOML < env vars.

2. **`core/model_client.py`** ✅ — `ModelClient.stream()` yields typed dataclass events (`OutputTextDelta`, `OutputItemDone`, `Completed`). Wraps `openai.AsyncOpenAI().responses.create(stream=True)`. Added transient-retry logic (max 2 attempts on 5xx/429/timeout). `_map_response_event()` keeps raw dicts fully isolated from callers. Added `ModelClientError`, `ModelClientSetupError`, `ModelClientStreamError` for clean error propagation.

3. **`core/session.py`** ✅ — `Session` with `append_user_message`, `append_assistant_message`, `append_tool_result`, `append_function_call`, `to_prompt()`. TypedDicts for all item variants. `to_prompt()` returns a detached copy. Tool results capped at 200K chars with a truncation marker. Expanded beyond spec: added `append_function_call` and `append_assistant_message` required by the agent loop.

4. **`tools/base.py`** ✅ — `ToolHandler` protocol, `ToolRegistry`, `ToolRouter`, `ToolResult`, `ToolError`, `ToolOutcome`, `serialize_tool_outcome`. `handle` returns `ToolOutcome = ToolResult | ToolError` (not a bare string as originally specced). Serialization to the model-facing JSON string is isolated in `serialize_tool_outcome`.

5. **`tools/shell.py`** ✅ — `ShellTool`. `asyncio.create_subprocess_exec(["bash", "-c", cmd])`. Default timeout 10s (not 120s as in spec — safer default). Output capped at 1MB. Returns `ToolResult` with JSON body containing `output`, `exit_code`, `duration_seconds`. `is_mutating` returns `True`.

6. **`tools/read_file.py`** ✅ — `ReadFileTool`. Line-numbered output with `L{n}:` prefix. Optional `offset`/`limit` (default 200, max 2000). Workspace-containment security check. Supports `response_format="json"` for metadata. Parallel read semaphore (max 4). Returns `ToolResult`. `is_mutating` returns `False`.

7. **`core/agent.py`** ✅ — `Agent` dataclass with `run_turn(user_input)`. Event system: `TurnStarted`, `ToolCallDispatched`, `ToolResultReceived`, `TurnCompleted`. Protocol interfaces `SupportsModelClient` and `SupportsToolRouter` for testability. Module-level `run_turn()` convenience wrapper. `on_event` callback supports both sync and async callables.

8. **`__main__.py`** ✅ — `main(argv)` + `_run_prompt(prompt)`. `ArgumentParser` for single positional `prompt`. Returns exit code 0/1. Error messages go to stderr, final answer to stdout.

---

#### Deviations from original spec

| Spec | Actual |
|---|---|
| `handle() -> str` | `handle() -> ToolOutcome` (T9 structured outcomes) |
| Shell default timeout 120s | 10s (more conservative for interactive use) |
| Shell returns plain string | Returns `ToolResult` with JSON body |
| `Session` has 3 append methods | 4 methods — added `append_function_call`, `append_assistant_message` |
| No retry in model client | 2-attempt transient retry with backoff |

---

#### Quality gates (all passing)

- `ruff check . --fix` — clean
- `ruff format .` — clean
- `mypy --strict pycodex/` — 12 source files, no issues
- `pytest tests/ -v` — **59 tests passing** (0 failures) — includes structured outcome tests for T9

---

**Key learnings**: Async agent loop; typed streaming events; Protocol-based tool dispatch; structured outcome types isolating failure modes; session-as-sole-history-mutator invariant; copy-on-read prompt snapshots.

**Test it**: `python -m pycodex "list the Python files in the current directory"`

---

### Milestone 2: Permission System + More Tools

**Goal**: Add approval prompts before mutating operations. Add file write, list_dir, grep tools.

**Codex references**: `codex-rs/protocol/src/approvals.rs`, `codex-rs/core/src/tools/sandboxing.rs`, `codex-rs/core/src/tools/orchestrator.rs`, `codex-rs/core/src/tools/handlers/{list_dir,grep_files,apply_patch}.rs`

---

**Status**: **Complete (implementation + tests)**. Milestone tracker and report archived at `archive/todo-m2.md`.

---

#### What shipped

1. **Approval store + policy (`approval/policy.py`)**
   - `ApprovalPolicy` + `ReviewDecision` enums implemented.
   - Deterministic key normalization via JSON serialization.
   - Pending-prompt coordination (`_pending_prompts` + `prompt_lock`) prevents duplicate concurrent prompts for the same approval key.
   - `APPROVED_FOR_SESSION` is cached; non-session decisions do not evict existing session approvals.

2. **Approval orchestrator (`tools/orchestrator.py`)**
   - Read-only bypass via `tool.is_mutating(args)`.
   - Policy behavior implemented for `never`, `on-failure`, `on-request`, `unless-trusted` (with M2 caveat below).
   - `DENIED` returns `ToolError(code="denied")`.
   - `ABORT` raises `ToolAborted` (terminal turn control flow).
   - Per-key prompt ownership/waiting behavior supports concurrent calls safely.

3. **Tooling surface**
   - New tools implemented and registered: `write_file`, `list_dir`, `grep_files`.
   - `write_file`: workspace containment + atomic write.
   - `list_dir`: sorted, depth-limited, paginated tree output.
   - `grep_files`: `rg` first, `grep` fallback, limit/truncation controls.

4. **Registry + agent integration**
   - `ToolRegistry` routes through orchestrator when configured.
   - `ToolAborted` intentionally propagates from registry to agent.
   - `core/agent.py` handles abort by emitting `TurnCompleted` and terminating the active turn immediately.

5. **CLI wiring (`__main__.py`)**
   - `--approval {never,on-failure,on-request,unless-trusted}` added.
   - `ask_user_fn` injected and implemented with `asyncio.to_thread(input, ...)`.
   - Default router includes `shell`, `read_file`, `write_file`, `list_dir`, `grep_files`.

6. **Approval-key contracts (post-hardening)**
   - `write_file`: approval key is resolved absolute target path.
   - `shell`: conservative canonicalization for wrapper-equivalent forms (`/bin/bash -lc` vs `bash -lc`), with semantically sensitive inline shell forms preserved as distinct keys.

---

#### Milestone 2 contract decisions to preserve

- `ABORT` is terminal control flow for the active turn; never downgrade it to a normal tool error continuation path.
- `DENIED` is non-terminal and returned to the model as structured tool error.
- Approval behavior is stateful only through `ApprovalStore`.
- `ON_FAILURE` escalation retry is deferred to Milestone 5 sandbox work; in M2 it behaves like auto-approve first attempt.

---

#### Verification snapshot (latest local run)

- `ruff check . --fix` — pass
- `ruff format .` — pass
- `mypy --strict pycodex/` — pass
- `pytest tests/ -v` — pass (`141 passed`, `1 skipped` live OpenAI e2e)

**Manual milestone verification caveat**:
- `python -m pycodex --approval on-request "create a file called test.txt with 'hello'"` requires local runtime setup (`openai` package + reachable endpoint) and may be blocked by environment.

**Key learning**: approval flow design, concurrent prompt dedupe, per-resource vs per-command key strategies, and clear terminal/non-terminal review decisions.

---

### Milestone 3: Event Protocol + JSONL Mode

**Goal**: Structured event protocol for programmatic use (like `codex exec --json`). Establishes the stable event contract that M4's TUI will consume.

**Status**: **Planned (next milestone)**.

**Non-goals**:
- No `item.updated` (streaming delta events) — deferred to M4 where the TUI needs them.
- No schema versioning or backward-compatibility guarantees.
- No event replay, persistence, or session recovery (M6).
- No WebSocket or SSE transport — JSONL stdout only.
- No changes to sequential tool dispatch — parallelism remains out of scope.

Current baseline before M3:
- `core/agent.py` already emits internal dataclass lifecycle callbacks (`turn_started`, `tool_call_dispatched`, `tool_result_received`, `turn_completed`) with `call_id` on tool events.
- `core/model_client.py` already emits typed stream events used by the agent (`OutputTextDelta`, `OutputItemDone`, `Completed`), but `Completed` currently carries `response_id` only. Token usage is not yet surfaced to agent events.
- There is no canonical protocol module yet (`pycodex/protocol/events.py` missing).
- There is no `--json` CLI mode yet; current entrypoint is `pycodex/__main__.py` (not `cli/app.py`).

#### Architecture: 3 layers

```
core/agent.py          internal AgentEvent dataclasses (unchanged)
        ↓
core/event_adapter.py  stateful mapper: AgentEvent → ProtocolEvent (new)
        ↓
__main__.py            renderer: text mode or JSONL mode (--json flag)
```

`agent.py` internal event types (`TurnStarted`, `ToolCallDispatched`, etc.) are **not replaced**. The adapter is the permanent translation layer, not a migration shim.

#### Milestone 3 execution plan (clear, incremental, verifiable)

1. **Define schema contract in `protocol/events.py`**
   - Root event discriminator is `type` (`thread.started`, `turn.started`, `turn.completed`, `turn.failed`, `item.started`, `item.completed`).
   - To avoid `type` collisions, item payload uses `item_kind` (not `type`) for details (`tool_call`, `tool_result`, `assistant_message`).
   - `TokenUsage`: `input_tokens: int`, `output_tokens: int` (optional on `turn.completed`).
   - All models use `model_config = ConfigDict(frozen=True)`.
   - Verification: `pytest tests/protocol/test_events.py -q`

2. **Implement deterministic ID strategy (owned by adapter)**
   - `thread_id`: generated once per run (default `uuid4()`), injectable in tests.
   - `turn_id`: monotonic adapter counter (`turn_1`, `turn_2`, ...), injectable start offset for tests.
   - `item_id`: reuse tool `call_id`; if missing/invalid, synthesize `item_<turn>_<ordinal>`.
   - Verification: `pytest tests/core/test_event_adapter.py::test_id_generation_and_reuse -q`

3. **Build `core/event_adapter.py` as permanent translation layer**
   - Consumes internal `AgentEvent`; emits protocol events through an output callback.
   - Maintains in-flight map keyed by `call_id` for `item.started -> item.completed` correlation.
   - Mapping:
     - `TurnStarted` -> `turn.started`
     - `ToolCallDispatched` -> `item.started`
     - `ToolResultReceived` -> `item.completed`
     - `TurnCompleted` -> `turn.completed`
   - ABORT remains intentional success: adapter emits `turn.completed` (not `turn.failed`).
   - Verification: `pytest tests/core/test_event_adapter.py -q`

4. **Plumb token usage to `turn.completed`**
   - Extend `core/model_client.py` `Completed` to optional usage payload when available from Responses API.
   - Thread usage through `core/agent.py` `TurnCompleted` and map to protocol `TokenUsage`.
   - If usage is unavailable, emit `usage: null` (or omit per schema choice) deterministically.
   - Verification: `pytest tests/core/test_model_client.py tests/core/test_agent.py -k usage -q`

5. **Add explicit `turn.failed` exception boundary in `__main__.py` JSON path**
   - In JSON mode, wrap turn execution so unhandled turn exceptions emit one `turn.failed` event before process exit.
   - Keep existing non-JSON error behavior unchanged.
   - Verification: `pytest tests/test_main.py -k \"json and failed\" -q`

6. **Add JSONL CLI mode and contract tests**
   - Add `--json` flag.
   - JSON mode: one serialized protocol event per line (`model_dump_json()`).
   - Text mode remains unchanged; JSON formatter and text formatter are separate paths.
   - Add deterministic CLI tests for line-delimited validity, ordering, and mandatory root `type`.
   - Verification: `pytest tests/cli/test_jsonl_mode.py -q`

#### Milestone 3 done criteria

- `--json` emits valid JSONL with a root `type` field on every line, for both text-only and tool-call flows.
- Adapter correctly reuses `call_id` as `item_id` across `item.started` -> `item.completed`.
- `turn.failed` is emitted on agent-loop exceptions; `turn.completed` is emitted on ABORT (not `turn.failed`).
- Token usage appears in `turn.completed` when available from the API; field is absent (or `null`) otherwise.
- Human text output mode is unchanged and unaffected by the adapter.
- `mypy --strict` passes on `protocol/` and `core/event_adapter.py`.
- `ruff check` and `ruff format` clean on all touched files.
- All new adapter unit tests pass with deterministic event sequences.

**Test it**: `python -m pycodex --json "what is 2+2" | python -c "import sys,json; [print(json.loads(l)['type']) for l in sys.stdin]"`

**Key learning target**: layered event architecture — internal lifecycle events, stateful public protocol adapter, and output-format-agnostic rendering. mirrors how Codex separates `exec_events.rs` from `event_processor_with_jsonl_output.rs`.

---

### Milestone 4: Interactive Terminal UI

**Goal**: Multi-turn interactive chat with streaming display and approval popups.

#### Milestone 4 execution plan (clear, incremental, verifiable)

1. **Build rendering primitives in `cli/display.py`**
   - Markdown, diff, and command-output render helpers with stable formatting contracts.
   - Value: isolates presentation logic from TUI event/state logic.
   - Verification: `pytest tests/cli/test_display.py -q`

2. **Build TUI shell in `cli/tui.py`**
   - Create baseline layout: history, input, status bar, and event queue wiring.
   - Value: runnable multi-turn skeleton before approval/streaming complexity.
   - Verification: `pytest tests/cli/test_tui_layout.py -q`

3. **Bind protocol events to UI timeline**
   - Render `ThreadEvent` items deterministically in chat history.
   - Value: M3 protocol becomes the single UI data contract.
   - Verification: `pytest tests/cli/test_tui_event_rendering.py -q`

4. **Integrate approval modal flow**
   - `ask_user_fn` opens `ApprovalModal` and returns `ReviewDecision`.
   - Value: removes blocking `input()` path and keeps approvals in UI loop.
   - Verification: `pytest tests/cli/test_tui_approval.py -q`

5. **Route entrypoints in `cli/app.py` and `__main__.py`**
   - Interactive default, `-p` single-turn, and `--json` protocol mode all coexist.
   - Value: one coherent interface surface for all runtime modes.
   - Verification: `pytest tests/test_main.py tests/cli/test_app_modes.py -q`

**Test it**: `python -m pycodex` → interactive chat, try "read the README.md file" then "create a test.py file" (should prompt for approval)

**Key learning**: TUI architecture, event-to-UI rendering, interactive approval flow, streaming display.

---

### Milestone 5: Sandboxing + Command Safety

**Goal**: Basic sandboxing for command execution and file operations.

#### Milestone 5 execution plan (clear, incremental, verifiable)

1. **Define sandbox policy domain in `approval/sandbox.py`**
   - Implement `SandboxPolicy`, path validation, and enforcement boundary API.
   - Value: explicit, testable policy model before command integration.
   - Verification: `pytest tests/approval/test_sandbox.py -q`

2. **Implement command classification in `approval/exec_policy.py`**
   - Prefix-rule matcher with `ALLOW | PROMPT | FORBIDDEN`.
   - Value: deterministic command-safety decisions independent of shell execution.
   - Verification: `pytest tests/approval/test_exec_policy.py -q`

3. **Integrate orchestrator sandbox flow**
   - First run under selected sandbox; escalate on failure only where policy allows.
   - Preserve M2 ABORT and DENIED semantics.
   - Value: defense-in-depth with explicit escalation path.
   - Verification: `pytest tests/tools/test_orchestrator.py -k sandbox -q`

4. **Optional OS-native sandbox adapters**
   - macOS `sandbox-exec`, Linux `firejail`/`bwrap`, with soft-sandbox fallback.
   - Value: stronger isolation where available without hard dependency.
   - Verification: `pytest tests/approval/test_sandbox_platform.py -q`

**Test it**: `python -m pycodex --sandbox workspace-write "try to delete /etc/hosts"` → blocked or prompts for escalation

**Key learning**: Defense in depth, sandbox escalation, command classification.

---

### Milestone 6: Context Management + Polish

**Goal**: Token tracking, auto-compaction, session persistence, configuration.

#### Milestone 6 execution plan (clear, incremental, verifiable)

1. **Token accounting service**
   - Add per-turn and cumulative usage tracking, surfaced to status bar and `turn.completed`.
   - Value: objective context-budget visibility.
   - Verification: `pytest tests/core/test_token_usage.py -q`

2. **Auto-compaction policy + executor**
   - Trigger near context window threshold; replace older context with deterministic summary block.
   - Value: keeps long sessions functional with bounded prompt growth.
   - Verification: `pytest tests/core/test_compaction.py -q`

3. **Session persistence and resume**
   - Persist history/config to `~/.pycodex/sessions/<id>.json`; add resume entrypoint.
   - Value: continuity across runs and recoverability after interruption.
   - Verification: `pytest tests/core/test_session_persistence.py tests/test_main.py -k resume -q`

4. **User config loading**
   - Add `~/.pycodex/config.toml` defaults and override precedence documentation/tests.
   - Value: reproducible local behavior without long CLI flags.
   - Verification: `pytest tests/core/test_config.py -k toml -q`

5. **Runtime resiliency pass**
   - Finalize retry/backoff, tool timeout boundaries, and Ctrl+C interruption behavior.
   - Value: safer long-running interactive operation.
   - Verification: `pytest tests/e2e/test_cli_tool_failures.py tests/e2e/test_interrupts.py -q`

**Test it**: Full multi-turn session with token tracking, save session, resume later.

---

## Key Codex Source Files to Study

| Python Module | Codex Reference File | What to Learn |
|---|---|---|
| `core/agent.py` | `codex-rs/core/src/codex.rs` (lines ~4744-6370) | Agent loop, sampling request, tool dispatch |
| `tools/base.py` | `codex-rs/core/src/tools/registry.rs` | ToolHandler trait, Registry, dispatch |
| `tools/orchestrator.py` | `codex-rs/core/src/tools/orchestrator.rs` | Approval → sandbox → execute → retry |
| `tools/shell.py` | `codex-rs/core/src/tools/handlers/shell.rs` | Shell execution, output formatting |
| `approval/policy.py` | `codex-rs/core/src/tools/sandboxing.rs` | ApprovalStore, ExecApprovalRequirement |
| `protocol/events.py` | `codex-rs/exec/src/exec_events.rs` | ThreadEvent, ThreadItem types |
| `approval/exec_policy.py` | `codex-rs/execpolicy/src/` | Command prefix rule engine |

## Simplifications vs. Full Codex

| Aspect | Codex (Full) | PyCodex (Simplified) |
|---|---|---|
| Language | Rust + TypeScript | Python only |
| Model API | Custom client, WebSocket + SSE | OpenAI Python SDK |
| Sandboxing | Seatbelt, seccomp+bubblewrap, restricted tokens | Path validation + optional sandbox-exec/firejail |
| Tool parallelism | `FuturesOrdered` with read/write locking | Sequential dispatch in agent loop (no parallel tool execution yet) |
| MCP support | Full MCP client + OAuth | Skipped (add later if desired) |
| Network proxy | Full MITM proxy | Skipped |
| Multi-agent | Agent spawn/wait/close | Skipped |
| Compaction | Remote API + inline compact | Local summarization |
| Skills/hooks | Full skill system, lifecycle hooks | Skipped |

## Verification Plan

After each milestone, verify with these tests:

- **M1**: `python -m pycodex "list files in current directory and show me the contents of pyproject.toml"` — model should call shell/read_file tools and return results
- **M2**: `python -m pycodex --approval on-request "create a file called test.txt with 'hello'"` — should prompt before writing
- **M3**: `python -m pycodex --json "what is 2+2"` — should emit valid JSONL events
- **M4**: `python -m pycodex` (interactive) — multi-turn chat with streaming text and approval popups
- **M5**: `python -m pycodex --sandbox read-only "rm -rf /"` — should block the command
- **M6**: Long conversation that triggers auto-compaction; save and resume session
