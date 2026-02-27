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

#### Design notes (informed by M1 + Codex source)

- **`ToolOutcome` is already the return type** — `handle()` returns `ToolResult | ToolError`. Orchestrator operates on `ToolOutcome` internally; `serialize_tool_outcome()` at the registry boundary is unchanged.
- **`is_mutating()` is already on all tools** — `ShellTool` returns `True`, `ReadFileTool` returns `False`. New tools just set the right value; no protocol changes needed.
- **Agent loop is unchanged** — orchestrator is injected at the `ToolRouter`/`ToolRegistry` layer. `core/agent.py` does not change.
- **`ask_user_fn` injected from `__main__.py`** — The non-interactive implementation uses `asyncio.to_thread(input, prompt)` (never blocking `input()`) to keep the event loop healthy.
- **Approval cache key = `json.dumps(key, sort_keys=True)`** — Codex serializes approval keys to JSON strings. For shell/write_file, the key is the full args dict; for `write_file` specifically, the key is the **absolute resolved file path** (matching Codex's `apply_patch` per-file caching pattern). This lets the user approve editing one file without approving edits to another.
- **`ApprovalStore.prompt_lock`** — asyncio lock serializes concurrent `ask_user_fn` calls so two simultaneous mutating tool calls don't interleave prompts in the terminal.
- **`DENIED` vs `ABORT`** — `DENIED` returns a `ToolError(code="denied")` to the model; the agent continues the turn normally (model can try something else). `ABORT` raises `ToolAborted`, caught by the agent loop, which emits a `TurnCompleted` with an abort message and stops.
- **`ApprovalPolicy.ON_FAILURE`** — auto-approve the first attempt; only prompt if execution fails (e.g. sandbox denial). This is Codex's retry-with-escalation pattern. For M2 (no sandbox yet) this behaves identically to `NEVER`; the escalation path is wired up properly in M5.
- **`write_file` → atomic write** — write to a `.tmp` sibling then `os.replace()`. Matches Codex's `std::fs::write` semantics; parent dirs created with `parents=True` if needed. Workspace-containment path check same as `read_file.py`.
- **`list_dir` → paginated, depth-limited tree** — Codex uses `offset`/`limit`/`depth` args (defaults: offset=1, limit=25, depth=2). Output is sorted by name; dirs get `/` suffix, symlinks get `@` suffix. Matches Codex's `list_dir.rs` exactly.
- **`grep_files` → `rg` first, `grep -rn` fallback** — Codex uses `rg --files-with-matches --sortr=modified --regexp <pattern> --glob <include>` with a 30s timeout. Returns file paths sorted by modification time (most recent first). Result limit: default 100, max 2000. Exit code 1 = no matches (not an error).

---

#### Files to create / update

1. **`approval/policy.py`** — Approval types and caching
   ```python
   class ApprovalPolicy(str, Enum):
       NEVER          = "never"           # Auto-approve everything; errors returned to model
       ON_FAILURE     = "on-failure"      # Auto-approve; prompt only if execution fails
       ON_REQUEST     = "on-request"      # Prompt for all mutating ops (default interactive)
       UNLESS_TRUSTED = "unless-trusted"  # Prompt unless command is known-safe read-only

   class ReviewDecision(str, Enum):
       APPROVED             = "approved"              # One-time approval
       APPROVED_FOR_SESSION = "approved_for_session"  # Cache for rest of session
       DENIED               = "denied"                # Reject; model can retry differently
       ABORT                = "abort"                 # Stop the turn immediately

   class ApprovalStore:
       _cache: dict[str, ReviewDecision]
       prompt_lock: asyncio.Lock   # Serialize concurrent approval prompts

       def get(self, key: object) -> ReviewDecision | None:
           return self._cache.get(json.dumps(key, sort_keys=True))

       def put(self, key: object, decision: ReviewDecision) -> None:
           self._cache[json.dumps(key, sort_keys=True)] = decision
   ```
   - For `write_file`: cache key = resolved absolute path (not full args dict), so per-file approval decisions are independent
   - For `shell`: cache key = full args dict (tool_name + command string)
   - Reference: `codex-rs/protocol/src/approvals.rs`, `codex-rs/core/src/tools/sandboxing.rs`

2. **`tools/orchestrator.py`** — Approval → execute flow
   ```python
   AskUserFn = Callable[[ToolHandler, dict[str, Any]], Awaitable[ReviewDecision]]

   class ToolAborted(Exception):
       def __init__(self, tool_name: str) -> None: ...

   async def execute_with_approval(
       tool: ToolHandler,
       args: dict[str, Any],
       cwd: Path,
       policy: ApprovalPolicy,
       store: ApprovalStore,
       ask_user_fn: AskUserFn,
   ) -> ToolOutcome:
       if not await tool.is_mutating(args):
           return await tool.handle(args, cwd)           # Read-only — skip approval

       key = _approval_key(tool, args)                   # Tool-specific key construction
       cached = store.get(key)
       if cached == ReviewDecision.APPROVED_FOR_SESSION:
           return await tool.handle(args, cwd)           # Previously approved for session

       if policy in (ApprovalPolicy.NEVER, ApprovalPolicy.ON_FAILURE):
           return await tool.handle(args, cwd)           # Auto-approve modes

       async with store.prompt_lock:                     # Serialize concurrent prompts
           decision = await ask_user_fn(tool, args)      # Non-blocking via asyncio.to_thread

       store.put(key, decision)

       if decision == ReviewDecision.ABORT:
           raise ToolAborted(tool.name)                  # Agent loop catches → stops turn
       if decision == ReviewDecision.DENIED:
           return ToolError(message="Operation denied by user.", code="denied")
       return await tool.handle(args, cwd)               # APPROVED or APPROVED_FOR_SESSION
   ```
   - Slotted inside `ToolRegistry.dispatch()` via an optional `OrchestratorConfig` dataclass — agent loop unchanged
   - Reference: `codex-rs/core/src/tools/orchestrator.rs`

3. **`tools/write_file.py`** — File writing
   - Args: `file_path: str`, `content: str`
   - Workspace-containment check (same pattern as `read_file.py`)
   - Atomic write: `path.with_suffix('.tmp')` → write → `os.replace(tmp, path)`
   - Creates parent directories if needed (`path.parent.mkdir(parents=True, exist_ok=True)`)
   - Returns `ToolResult(body={"path": str, "bytes_written": int})`
   - `is_mutating() = True`; approval key = resolved absolute path (not full args)
   - Later milestone: evolve to unified-diff patch via `apply_patch`
   - Reference: `codex-rs/core/src/tools/handlers/apply_patch.rs` + `codex-rs/apply-patch/src/lib.rs`

4. **`tools/list_dir.py`** — Directory listing
   - Args: `dir_path: str`, `offset: int = 1` (1-indexed), `limit: int = 25`, `depth: int = 2`
   - Sorted by name; directories suffixed `/`, symlinks suffixed `@`
   - Tree-indented output (2 spaces per depth level)
   - Pagination: include "… N more entries" message when truncated
   - Entry display truncated at 500 chars
   - Returns `ToolResult(body=str)` — plain text listing
   - `is_mutating() = False`
   - Reference: `codex-rs/core/src/tools/handlers/list_dir.rs`

5. **`tools/grep_files.py`** — Content search
   - Args: `pattern: str`, `path: str | None`, `include: str | None` (glob), `limit: int = 100`
   - Max limit: 2000; results sorted by modification time (most recent first)
   - Command: `rg --files-with-matches --sortr=modified --regexp <pattern> [--glob <include>] -- <path>`
   - Timeout: 30s; exit code 1 = no matches (return empty list, not error)
   - Falls back to `grep -rl <pattern> <path>` if `rg` not found
   - Returns `ToolResult(body={"matches": [str], "truncated": bool})`
   - `is_mutating() = False`
   - Reference: `codex-rs/core/src/tools/handlers/grep_files.rs`

6. **`__main__.py`** — Add `--approval` flag
   - `--approval {never,on-failure,on-request,unless-trusted}` (default: `never`)
   - Build `ApprovalStore`, wire non-interactive `ask_user_fn` using `asyncio.to_thread(input, prompt)`
   - Pass `OrchestratorConfig(policy, store, ask_user_fn)` into `ToolRegistry` before constructing the agent

---

#### What does NOT change

- `core/agent.py` — untouched; `ToolAborted` is caught at the `ToolRegistry.dispatch()` level and converted to a `ToolError` before reaching the agent, or propagated up if ABORT
- `core/model_client.py`, `core/session.py`, `core/config.py` — no changes
- `tools/base.py`, `tools/shell.py`, `tools/read_file.py` — no changes; orchestrator wraps transparently

---

#### Risk areas

| Risk | Mitigation |
|---|---|
| Blocking `input()` stalls event loop | Use `asyncio.to_thread(input, prompt)` |
| Concurrent mutating calls interleave prompts | `ApprovalStore.prompt_lock` serializes `ask_user_fn` calls |
| Cache key collisions on dict arg order | `json.dumps(key, sort_keys=True)` — order-independent |
| `ABORT` silently drops the turn | Raise `ToolAborted`; agent loop catches and emits abort message |
| `write_file` escapes workspace | Same `cwd`-containment check as `read_file.py` |
| `grep_files` `rg` not installed | Detect via `shutil.which("rg")`; fall back to `grep -rl` |
| `ON_FAILURE` escalation not wired yet | Correct in M2 (behaves as `NEVER`); sandbox retry added in M5 |

---

#### Done criteria

- `python -m pycodex --approval on-request "create a hello.py file that prints hello world"` prompts before writing
- `python -m pycodex --approval never "create a hello.py file"` writes without prompting
- `APPROVED_FOR_SESSION` skips prompt on second identical call within same session
- `DENIED` returns a clean error to the model; turn continues
- `ABORT` stops the turn with a clear message
- `list_dir` and `grep_files` never prompt (read-only)
- All quality gates pass (`ruff`, `mypy --strict`, `pytest`)

**Test it**: `python -m pycodex --approval on-request "create a hello.py file that prints hello world"`

**Key learning**: Approval flow, per-resource session caching, mutating vs read-only distinction, async-safe user prompting, `rg`/`grep` subprocess pattern.

---

### Milestone 3: Event Protocol + JSONL Mode

**Goal**: Structured event protocol for programmatic use (like `codex exec --json`).

**Files to create**:

1. **`protocol/events.py`** — All event types as Pydantic models
   ```python
   class ThreadEvent(BaseModel):
       type: str

   class ThreadStartedEvent(ThreadEvent):
       type: Literal["thread.started"] = "thread.started"
       thread_id: str

   class ItemStartedEvent(ThreadEvent):
       type: Literal["item.started"] = "item.started"
       item: ThreadItem

   class ThreadItem(BaseModel):
       id: str
       details: ThreadItemDetails  # discriminated union

   class AgentMessageItem(BaseModel):
       type: Literal["agent_message"] = "agent_message"
       content: str
       status: str  # "in_progress" | "completed"

   class CommandExecutionItem(BaseModel):
       type: Literal["command_execution"] = "command_execution"
       command: str
       output: str | None
       exit_code: int | None
       status: str
   ```
   - Reference: `codex-rs/exec/src/exec_events.rs` — `ThreadEvent`, `ThreadItem`, `ThreadItemDetails` enums

2. **Update `core/agent.py`** — Emit events at each lifecycle point
   - `thread.started` at session init
   - `turn.started` before model call
   - `item.started/updated/completed` for tool calls and agent messages
   - `turn.completed` with usage stats

3. **`cli/app.py`** — Add `--json` flag
   - JSON mode: emit JSONL to stdout (one event per line)
   - Text mode: print human-readable output (default)

#### Milestone 3 Implementation Checklist (Richer Item Event Handling)

Use this checklist when implementing M3 so event handling scope is explicit:

1. **Expand model stream event surface in `core/model_client.py`**
   - Add typed events for item lifecycle and richer stream payloads:
     - `OutputItemAdded`
     - `OutputItemDone` (already present; keep as the completion trigger for tool-call execution)
     - `OutputTextDelta` (already present)
     - `Completed` (already present)
   - Keep dataclass-only event outputs (no raw dict events crossing module boundaries).

2. **Define canonical thread/item event schemas in `protocol/events.py`**
   - Add `ThreadEvent` + `ThreadItem` discriminated unions for:
     - agent message items (started/updated/completed)
     - tool call items (started/completed)
   - Include stable ids (`thread_id`, `turn_id`, `item_id`, `tool_call_id` where relevant).

3. **Map model events to lifecycle events in `core/agent.py`**
   - Emit `item.started` when an output item is added.
   - Emit `item.updated` on text deltas for active assistant items.
   - Emit `item.completed` when an output item is done.
   - Execute tool calls only from completed tool-call items, then emit tool result completion events.
   - Emit `turn.started`/`turn.completed` around each sampling request loop.

4. **Wire JSONL emission in `cli/app.py`**
   - `--json` mode prints serialized `ThreadEvent` records, one line per event.
   - Preserve current human-readable mode behavior when `--json` is not set.

5. **Add deterministic verification tests**
   - Unit tests for event mapping and schema validation.
   - Agent integration test asserting ordered lifecycle sequence for:
     - a no-tool turn
     - a tool-call turn with follow-up model iteration
   - Assert contract fields and ids, not prose text content.

#### Milestone 3 Done Criteria

- `--json` emits valid JSONL lifecycle events for text + tool-call flows.
- Tool calls are sourced from completed output items and represented as explicit item lifecycle events.
- Event stream is reproducible/deterministic in tests (no live network dependency).
- Quality gates pass for touched modules (`ruff`, targeted `pytest`, `mypy --strict` on touched packages).

**Test it**: `python -m pycodex --json "what OS am I running?" | python -c "import sys,json; [print(json.loads(l)['type']) for l in sys.stdin]"`

**Key learning**: Event-driven architecture, separation of core engine from presentation.

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
| Tool parallelism | `FuturesOrdered` with read/write locking | `asyncio.gather()` with sequential fallback for mutating |
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
