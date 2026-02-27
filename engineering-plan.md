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

### Milestone 1: Minimal Agent Loop (Non-Interactive)

**Goal**: A CLI that takes a prompt, calls a model, executes tool calls, loops until done, and prints the result.

**Files to create**:

1. **`core/config.py`** — Pydantic `Config` model
   - Fields: `model`, `api_key` (from `OPENAI_API_KEY` env), `api_base_url`, `cwd`
   - Load from env vars + optional `pycodex.toml`

2. **`core/model_client.py`** — Async streaming model client
   - `ModelClient.stream(messages, tools) -> AsyncIterator[ResponseEvent]`
   - Wraps `openai.AsyncOpenAI().responses.create(stream=True)`
   - `ResponseEvent` dataclass variants: `OutputTextDelta`, `OutputItemDone`, `Completed`
   - Key reference: the Codex pattern of iterating over response stream events and collecting tool call items

3. **`core/session.py`** — Session state
   - `Session` class: holds message history (list of response input items), config, event callbacks
   - `append_user_message()`, `append_tool_result()`, `to_prompt() -> list`

4. **`tools/base.py`** — Tool system foundation
   - `ToolHandler` protocol:
     ```python
     class ToolHandler(Protocol):
         name: str
         def tool_spec(self) -> dict: ...          # JSON schema for API
         async def is_mutating(self, args: dict) -> bool: ...
         async def handle(self, args: dict, cwd: Path) -> str: ...
     ```
   - `ToolRegistry`: `dict[str, ToolHandler]`, `register()`, `dispatch(name, args)`
   - `ToolRouter`: builds tool spec list for API, routes model tool_call items to handlers

5. **`tools/shell.py`** — Shell execution
   - `asyncio.create_subprocess_exec(["bash", "-c", command])`
   - Capture stdout+stderr with configurable timeout (default 120s)
   - Return formatted output: exit code + truncated output
   - Reference: `codex-rs/core/src/tools/handlers/shell.rs`

6. **`tools/read_file.py`** — File reading
   - Accept `file_path`, optional `offset`/`limit`
   - Return content with line numbers (like `cat -n`)
   - Reference: `codex-rs/core/src/tools/handlers/read_file.rs`

7. **`core/agent.py`** — The core agent loop
   ```python
   async def run_turn(session, user_input):
       session.append_user_message(user_input)
       while True:
           # Stream model response
           tool_calls, text = await _run_sampling_request(session)
           if not tool_calls:
               return text  # Done — model gave final answer
           # Execute tool calls concurrently
           results = await asyncio.gather(*[
               router.dispatch(tc) for tc in tool_calls
           ])
           # Append results to history, loop for follow-up
           for tc, result in zip(tool_calls, results):
               session.append_tool_result(tc.call_id, result)
   ```
   - Reference: `codex-rs/core/src/codex.rs` lines ~4744-5104 (`run_turn`)

8. **`__main__.py`** — CLI entry point
   - Parse prompt from args, call `run_turn()`, print result

**Test it**: `python -m pycodex "list the Python files in the current directory"`

**Key learning**: The agent loop pattern, streaming responses, tool dispatch, concurrent execution.

---

### Milestone 2: Permission System + More Tools

**Goal**: Add approval prompts before mutating operations. Add file write, list_dir, grep tools.

**Files to create**:

1. **`approval/policy.py`** — Approval types and caching
   - `ApprovalPolicy` enum: `NEVER`, `ON_FAILURE`, `ON_REQUEST`, `UNLESS_TRUSTED`
   - `ReviewDecision` enum: `APPROVED`, `APPROVED_FOR_SESSION`, `DENIED`, `ABORT`
   - `ApprovalStore`: session-scoped cache (`dict[str, ReviewDecision]`)
     - Cache key = serialized (tool_name, command/path)
     - `APPROVED_FOR_SESSION` decisions cached for matching future calls
   - Reference: `codex-rs/core/src/tools/sandboxing.rs` — `ApprovalStore`, `ExecApprovalRequirement`

2. **`tools/orchestrator.py`** — Approval → execute flow
   ```python
   async def execute_with_approval(tool, args, policy, store, ask_user_fn):
       if not await tool.is_mutating(args):
           return await tool.handle(args)   # Read-only — skip approval
       cached = store.get(approval_key(tool, args))
       if cached == APPROVED_FOR_SESSION:
           return await tool.handle(args)   # Previously approved
       if policy == NEVER:
           return await tool.handle(args)   # Auto-approve mode
       decision = await ask_user_fn(tool, args)  # Ask user
       store.put(approval_key(tool, args), decision)
       if decision in (APPROVED, APPROVED_FOR_SESSION):
           return await tool.handle(args)
       raise ToolDenied(...)
   ```
   - Reference: `codex-rs/core/src/tools/orchestrator.rs` lines ~100-323

3. **`tools/write_file.py`** — File writing
   - Simple: accept `file_path` + `content`, write file
   - `is_mutating() = True` — always requires approval
   - Later: evolve to unified-diff patching (apply_patch)

4. **`tools/list_dir.py`** — Directory listing
   - Accept `path`, return formatted file listing with sizes/types

5. **`tools/grep_files.py`** — Content search
   - Accept `pattern`, `path`, optional `include` glob
   - Use `subprocess` to run `grep -rn` or implement with `pathlib` + `re`

6. **Update `core/agent.py`** — Wire tool dispatch through orchestrator
   - Non-interactive: use `input()` for approval prompts (simple but functional)

**Test it**: `python -m pycodex --approval on-request "create a hello.py file that prints hello world"`

**Key learning**: Approval flow, session caching, mutating vs read-only distinction.

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
