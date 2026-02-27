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

**Goal**: Structured event protocol for programmatic use (like `codex exec --json`).

**Status**: **Planned (next milestone)**.

Current baseline before M3:
- `core/agent.py` already emits internal dataclass lifecycle callbacks (`turn_started`, `tool_call_dispatched`, `tool_result_received`, `turn_completed`).
- `core/model_client.py` already emits typed stream events used by the agent (`OutputTextDelta`, `OutputItemDone`, `Completed`).
- There is no canonical protocol module yet (`pycodex/protocol/events.py` missing).
- There is no `--json` CLI mode yet; current entrypoint is `pycodex/__main__.py` (not `cli/app.py`).

#### Milestone 3 execution plan (updated for current repo structure)

1. **Create canonical protocol models in `protocol/events.py`**
   - Define Pydantic models for thread/turn/item lifecycle events:
     - `thread.started`
     - `turn.started`, `turn.completed`
     - `item.started`, `item.updated`, `item.completed`
   - Define discriminated `ThreadItem` details for:
     - assistant message lifecycle
     - tool-call lifecycle
     - tool-result lifecycle
   - Include stable IDs (`thread_id`, `turn_id`, `item_id`, `tool_call_id` where applicable).

2. **Adapt `core/agent.py` to emit protocol events**
   - Keep current behavioral ordering, but emit protocol events instead of ad-hoc internal-only dataclasses (or provide a compatibility adapter during migration).
   - Preserve existing ABORT semantics (`ToolAborted` => terminal `turn.completed`).
   - Ensure tool calls continue to execute only from completed tool-call output items.

3. **Add JSONL mode in current entrypoint (`pycodex/__main__.py`)**
   - Add `--json` flag.
   - In JSON mode, stream one serialized protocol event per line to stdout.
   - Preserve existing text mode behavior and error handling.

4. **Expand model-client stream typing only as needed**
   - Add `OutputItemAdded` only if required to support item-start semantics cleanly.
   - Keep raw SDK dicts encapsulated inside `model_client.py`.

5. **Add deterministic tests (contract-first)**
   - Unit tests for protocol model validation/serialization.
   - Agent integration tests for ordered lifecycle events:
     - no-tool turn
     - tool-call turn with follow-up iteration
     - abort turn path (terminal completion)
   - CLI tests for `--json` output shape and line-delimited validity.

#### Milestone 3 done criteria

- `--json` emits valid JSONL protocol events for both text-only and tool-call flows.
- Event stream has stable IDs and deterministic ordering in tests.
- ABORT semantics remain unchanged under protocol/JSON mode.
- Quality gates pass for touched scope (`ruff`, targeted `pytest`, `mypy --strict` on touched packages).

**Test it**: `python -m pycodex --json "what is 2+2" | python -c "import sys,json; [print(json.loads(l)['type']) for l in sys.stdin]"`

**Key learning target**: standardized event contracts and clean separation between core lifecycle events and presentation/output mode.

---

### Milestone 4: Interactive Terminal UI

**Goal**: Multi-turn interactive chat with streaming display and approval popups.

**Files to create**:

1. **`cli/display.py`** — Rich rendering utilities
   - `render_markdown(text) -> rich.Text` — markdown with syntax highlighting
   - `render_diff(patch) -> rich.Text` — colored unified diff
   - `render_command(cmd, output, exit_code) -> rich.Panel` — command result display
   - Uses `rich.markdown.Markdown`, `rich.syntax.Syntax`

2. **`cli/tui.py`** — Textual TUI application
   - Layout: scrollable chat history + text input + status bar
   - `ChatView` widget: renders `ThreadItem` events with rich formatting
   - `InputArea` widget: text input with Enter to send, Ctrl+C to interrupt
   - `ApprovalModal` widget: shows tool call details, approve/deny/approve-for-session buttons
   - `StatusBar` widget: model name, token usage, agent status
   - Receives `ThreadEvent` from agent core via async message queue
   - Streaming text: characters appear progressively (driven by `OutputTextDelta` events)

3. **`cli/app.py`** — Update entry point
   - No args / interactive mode → launch TUI
   - `--json` flag → JSONL mode
   - `-p "prompt"` → single-turn non-interactive mode

4. **Wire approval into TUI**
   - `ask_user_fn` callback opens `ApprovalModal` and awaits user selection
   - Replaces `input()` from Milestone 2

**Test it**: `python -m pycodex` → interactive chat, try "read the README.md file" then "create a test.py file" (should prompt for approval)

**Key learning**: TUI architecture, event-to-UI rendering, interactive approval flow, streaming display.

---

### Milestone 5: Sandboxing + Command Safety

**Goal**: Basic sandboxing for command execution and file operations.

**Files to create**:

1. **`approval/sandbox.py`** — Sandbox policies
   - `SandboxPolicy` enum: `READ_ONLY`, `WORKSPACE_WRITE`, `FULL_ACCESS`
   - `PathValidator`: check if a path is within workspace bounds
   - `SandboxManager`: select sandbox level, validate paths
   - Reference: `codex-rs/core/src/sandboxing/` — `SandboxPolicy` enum, `SandboxManager`

2. **`approval/exec_policy.py`** — Command prefix rules
   - Default safe commands: `ls`, `cat`, `pwd`, `echo`, `git status`, `git diff`, `python --version`, etc.
   - Default dangerous: `rm -rf`, `sudo`, `chmod`, etc.
   - `ExecPolicy.check(command) -> ALLOW | PROMPT | FORBIDDEN`
   - Reference: `codex-rs/execpolicy/src/` — prefix-based rule matching

3. **Optional platform sandboxing**:
   - macOS: wrap commands with `sandbox-exec -p '(deny default)(allow ...)' bash -c "..."`
   - Linux: wrap with `firejail --noprofile --quiet` or `bwrap` if available
   - Fallback: path-based validation only (soft sandbox)

4. **Update orchestrator** — Sandbox selection flow
   - First attempt: run in sandbox
   - On sandbox failure + `ON_FAILURE` policy: prompt user to escalate
   - Reference: `codex-rs/core/src/tools/orchestrator.rs` retry-with-escalation pattern

**Test it**: `python -m pycodex --sandbox workspace-write "try to delete /etc/hosts"` → blocked or prompts for escalation

**Key learning**: Defense in depth, sandbox escalation, command classification.

---

### Milestone 6: Context Management + Polish

**Goal**: Token tracking, auto-compaction, session persistence, configuration.

**What to build**:

1. **Token tracking** — Use `tiktoken` to count tokens per turn
   - Display in status bar and turn completion events
   - Track cumulative usage across turns

2. **Auto-compaction** — When approaching context window limit
   - Strategy: summarize older messages into a compact context block
   - Simple approach: call the model to "summarize the conversation so far", replace older history
   - Reference: Codex's `run_auto_compact()` in `codex.rs`

3. **Session persistence** — Save/resume conversations
   - Save session state (history, config) to `~/.pycodex/sessions/<id>.json`
   - `--resume <id>` flag to continue a conversation
   - Reference: `codex-rs/core/src/message_history.rs`

4. **Config file** — `~/.pycodex/config.toml`
   - Model, API key, default approval policy, sandbox policy
   - Custom system instructions
   - Default tools to enable

5. **Error handling** — Graceful API error recovery
   - Exponential backoff on rate limits
   - Timeout handling for long-running tools
   - Ctrl+C interruption during model streaming

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
