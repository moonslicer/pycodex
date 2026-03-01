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
    "rich>=13.0",        # Terminal formatting, markdown, syntax highlight (text mode)
    "tiktoken>=0.5",     # Token counting
    # Note: textual removed — TUI layer is TypeScript (React + Ink + Yoga)
]
```

**TypeScript TUI dependencies** (`tui/package.json`, M4+):
```json
{
  "dependencies": {
    "react": "^18",
    "ink": "^5",
    "yoga-layout": "^3"
  },
  "devDependencies": {
    "typescript": "^5",
    "@types/react": "^18",
    "ink-testing-library": "^3",
    "ts-jest": "^29"
  }
}
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

**Status**: **Complete (implementation + tests)**. Milestone tracker: `todo-m3.md`.

**Non-goals**:
- No `item.updated` (streaming delta events) — deferred to M4 where the TUI needs them.
- No schema versioning or backward-compatibility guarantees.
- No event replay, persistence, or session recovery (M6).
- No WebSocket or SSE transport — JSONL stdout only.
- No changes to sequential tool dispatch — parallelism remains out of scope.

#### What shipped

1. **Protocol package (`pycodex/protocol/events.py`)**
   - Added frozen Pydantic models for `thread.started`, `turn.started`, `turn.completed`, `turn.failed`, `item.started`, `item.completed`.
   - Added discriminated union `ProtocolEvent` keyed by root `type`.
   - Added `TokenUsage(input_tokens, output_tokens)` with strict integer validation.

2. **Stateful adapter (`pycodex/core/event_adapter.py`)**
   - Added deterministic ID strategy:
     - `thread_id`: per-adapter, injectable.
     - `turn_id`: `turn_1`, `turn_2`, ...
     - `item_id`: reuse `call_id` with deterministic fallback.
   - Added mapping from internal `AgentEvent` dataclasses to protocol events.
   - Added explicit one-time thread start guard: duplicate `start_thread()` now raises.
   - Preserved ABORT contract: ABORT still maps to `turn.completed` (not `turn.failed`).

3. **Usage threading (`pycodex/core/model_client.py`, `pycodex/core/agent.py`)**
   - Extended stream `Completed` event to carry optional usage when available.
   - Threaded usage through agent lifecycle into protocol `turn.completed.usage`.

4. **JSONL CLI mode (`pycodex/__main__.py`)**
   - Added `--json` mode.
   - Emits one serialized protocol event per line.
   - Added JSON-mode exception boundary that emits `turn.failed` and exits non-zero.
   - Kept human text mode unchanged and separate.

5. **Test coverage**
   - Added/extended:
     - `tests/protocol/test_events.py`
     - `tests/core/test_event_adapter.py`
     - `tests/core/test_model_client.py`
     - `tests/core/test_agent.py`
     - `tests/test_main.py`
     - `tests/e2e/test_cli_json_contract.py`

#### Verification snapshot (latest local run)

- `ruff check . --fix` — pass
- `ruff format .` — pass
- `mypy --strict pycodex/` — pass (`21 source files`)
- `pytest tests/ -v` — pass (`187 passed, 1 skipped`)
- Milestone verification command:
  - `python3 -m pycodex --json "what is 2+2"`
  - observed event flow: `thread.started` → `turn.started` → `turn.completed` (with `usage`)

**Key learning**: layered event architecture with a stable protocol boundary: internal agent callbacks stay implementation-focused, while `EventAdapter` owns deterministic public event identity and JSONL emission contracts.

---

### Milestone 4: Interactive Terminal UI

**Goal**: Multi-turn interactive chat with streaming display and approval popups.

**Architecture**: TypeScript (React + Ink + Yoga) is the entry point and display layer. It spawns Python as a child process. Communication is over stdio pipes using a JSON-RPC envelope — the same framing used by LSP and MCP over stdio. Python's existing `--json` JSONL event stream is the data source; a new `--tui-mode` flag enables Python to also read JSON-RPC commands from stdin.

**Language boundary**: Python owns the agent brain (model calls, tool execution, approval decisions). TypeScript owns display, input, and approval UI. Neither side knows the internals of the other — they communicate only through the JSONL/JSON-RPC protocol.

**Wire protocol**:
```
Python stdout → JSONL (one ProtocolEvent per line, M3 format + new events)
TypeScript stdin write → JSON-RPC commands

Python emits:   thread.started, turn.started, turn.completed, turn.failed,
                item.started, item.completed, item.updated (M4C),
                approval.request (M4D)

TypeScript sends: user.input, approval.response, interrupt
```

Detailed sub-milestone breakdown is in `tui-plan.md`. Summary of execution plan:

#### Milestone 4 execution plan (clear, incremental, verifiable)

1. **M4A — Protocol scaffold (TypeScript)**
   - TypeScript: scaffold `tui/` package (React + Ink + Yoga), strict TS config, and protocol layer (`types.ts`, `reader.ts`, `writer.ts`, stdio transport) with focused protocol tests.
   - Value: verifies toolchain + protocol boundary before introducing Python bridge or UI lifecycle complexity.
   - Verification: `cd tui && tsc --noEmit && eslint src/ && jest`

2. **M4B — Python pipe protocol + TypeScript Ink shell**
   - Python: add `--tui-mode` flag; implement `core/tui_bridge.py` (asyncio stdin reader + JSON-RPC command dispatcher; routes `user.input` → `run_turn()`, `interrupt` → task cancel).
   - TypeScript: implement `src/index.ts` (spawn Python, pipe lifecycle), `app.tsx` (root Ink component), `ChatView`, `InputArea`, `StatusBar`.
   - Value: runnable multi-turn Ink chat over stdio; full bidirectional architecture established.
   - Verification: `pytest tests/core/test_tui_bridge.py -q` + `jest tui/ -q` + `node tui/dist/index.js` multi-turn chat works.

3. **M4C — Streaming text (`item.updated`)**
   - Python: add `ItemUpdated` event to `protocol/events.py`; surface `OutputTextDelta` through adapter as `item.updated`.
   - TypeScript: add `item.updated` to `types.ts`; implement `LineBuffer` in `ChatView.tsx` (newline-gated commit; simpler than Codex's 3-layer `StreamController`).
   - Value: model response text appears progressively; `item.updated` is now part of the stable protocol (existing `--json` consumers see it too).
   - Verification: `pytest tests/protocol/test_events.py tests/core/test_event_adapter.py -k updated -q` + `jest tui/ -q`

4. **M4D — Approval modal**
   - Python: add `ApprovalRequested` event to `protocol/events.py`; implement `tui_ask_user_fn` in `tui_bridge.py` (emits `approval.request`, awaits `approval.response` via `asyncio.Event`, returns `ReviewDecision`).
   - TypeScript: add `ApprovalModal.tsx` (key bindings: `y/n/s/a`; queue of pending requests); route `approval.request` event → modal state; on key press send `approval.response` command.
   - Value: removes blocking `input()` path; approval is now a first-class UI event with a clean request/response ID protocol.
   - Verification: `pytest tests/core/test_tui_bridge.py -k approval -q` + `jest tui/ -q` + manual tool-call approval test.

5. **M4E — Tool call panels + interrupt + status polish**
   - TypeScript: extend `ChatView` to render `item.started`/`item.completed` as inline bordered tool panels (keyed by `item_id`); extend `StatusBar` with cumulative token usage from `turn.completed.usage`; wire Ctrl+C → `writer.sendInterrupt()`.
   - Python: `tui_bridge.py` handles `interrupt` command → cancel active turn task.
   - Value: full visibility into tool call lifecycle; clean Ctrl+C cancellation; token budget visible.
   - Verification: `jest tui/ -q` + `pytest tests/core/test_tui_bridge.py -k interrupt -q` + manual tool-panel test.

**Test it**: `node tui/dist/index.js` → interactive chat; try "read the README.md file" then "create a test.py file" (approval modal appears); Ctrl+C mid-turn cancels cleanly.

**Key learning**: TypeScript/Python process boundary; JSON-RPC framing over stdio pipes; React + Ink component model; bidirectional request/response protocol with asyncio.Event suspension; transport-agnostic envelope design (pipes now, WebSocket in M6).

---

### Milestone 5: Sandboxing + Command Safety

**Goal**: Add defense-in-depth for shell command execution — classify commands before they run and optionally wrap them in OS-level isolation.

**Design reference**: Informed by Codex's `execpolicy`, `sandboxing.rs`, and `orchestrator.rs`. Key patterns adopted where they improve the design without adding disproportionate complexity. Deferred: Starlark policy format, execpolicy amendments, network rules, `RejectConfig`, Windows sandbox.

**Architecture constraints from actual codebase:**
- `ShellTool.is_mutating()` is always `True` — exec classification is **not** a replacement for `is_mutating()`. It is an additional short-circuit inside the orchestrator, evaluated after `is_mutating()`, before the approval prompt.
- `ShellTool.handle()` signature stays stable (part of `ToolHandler` protocol). OS-native sandbox wrappers are an **optional duck-typed method** `sandbox_execute(args, cwd, policy)` on `ShellTool` — the same pattern used by `approval_key`. Orchestrator uses `getattr(tool, "sandbox_execute", None)` and falls back to `handle()`.
- `OrchestratorConfig` is `frozen=True` — new optional fields are additive; existing call sites unchanged.

**Layer semantics**: exec policy and sandbox policy are independent, additive layers. Neither bypasses the other — `ALLOW` from exec policy skips the approval prompt but sandbox still runs under restrictive policies. `danger-full-access` disables sandbox wrapping but approval follows `ApprovalPolicy` normally. Both guardrails must be explicitly opted out of, separately.

#### Milestone 5 execution plan (clear, incremental, verifiable)

1. **Command classification in `approval/exec_policy.py`**
   - Define `ExecDecision` enum: `ALLOW | PROMPT | FORBIDDEN`.
   - Implement `classify(command: str, rules: list[tuple[str, ExecDecision]], heuristics: Callable[[str], ExecDecision] | None = None) -> ExecDecision`. Rules are checked in order against the **canonicalized** command string (same normalization as `_canonicalize_command_for_approval` in `shell.py` — handles wrapper forms like `/bin/bash -lc`, whitespace, and equivalent aliases). Matching is **token-boundary aware**: a prefix matches only when the stripped command equals the prefix exactly or the next character is ASCII whitespace — bare-word entries like `"ls"` must not match `lsof`, `catapult`, or similar commands that share the same leading characters. First match wins; if no rule matches, call `heuristics(command)` (original un-stripped input) if provided, else return `PROMPT`.
   - Export `DEFAULT_RULES` and `default_heuristics` as importable defaults, not hardcoded into `classify`. Both can be overridden or extended by callers. `DEFAULT_RULES` FORBIDDEN entries use the broader `"rm -rf"` prefix (catches all targets, not just `/` and `~`).
   - The classifier is a pure function — no I/O, no side effects.
   - Value: deterministic command-safety decisions independent of execution context; canonicalization closes the most common evasion vectors.
   - Verification: `pytest tests/approval/test_exec_policy.py -q`

2. **Sandbox policy domain in `approval/sandbox.py`**
   - Define `SandboxPolicy` enum with three values (Codex-aligned naming):
     - `danger-full-access` — no sandbox wrapping; approval policy applies normally. The name signals the user is accepting unsandboxed execution risk.
     - `read-only` — process may not write to the filesystem.
     - `workspace-write` — process may write only within `cwd`; all other paths are read-only.
   - Expose `build_sandbox_argv(command: str, policy: SandboxPolicy, cwd: Path) -> list[str]` — returns full argv for `asyncio.create_subprocess_exec`. Under `danger-full-access`, returns `["bash", "-c", command]` unchanged.
   - Platform adapters: macOS `sandbox-exec` with a minimal inline seatbelt profile; Linux `firejail --quiet` if available, `bwrap` as fallback. If no native sandbox is present under a restrictive policy (`read-only` or `workspace-write`), emit a warning to stderr and surface `SandboxUnavailable` — do not silently no-op and proceed as if protected.
   - Value: isolation tested independently before orchestrator wiring; fail-visible not fail-open.
   - Verification: `pytest tests/approval/test_sandbox.py -q`

3. **Wire exec policy + sandbox into the orchestrator**
   - Add two optional fields to `OrchestratorConfig`:
     - `exec_policy_fn: Callable[[str], ExecDecision] | None = None`
     - `sandbox_policy: SandboxPolicy | None = None`
   - New code path in `execute_with_approval()`, after `is_mutating()`. Decision matrix (evaluated in order, first match wins):

   | exec_policy result | sandbox_policy | approval_policy | Outcome |
   |---|---|---|---|
   | `FORBIDDEN` | any | any | `ToolError(code="forbidden")` — no sandbox, no prompt |
   | `ALLOW` | `danger-full-access` or unset | any | `tool.handle()` — sandbox disabled, prompt skipped |
   | `ALLOW` | `read-only` or `workspace-write` | any | `tool.sandbox_execute()` — sandbox runs, prompt skipped |
   | `PROMPT` or unset | `danger-full-access` or unset | `NEVER` / `ON_FAILURE` | `tool.handle()` — no sandbox, no prompt (existing behavior) |
   | `PROMPT` or unset | `danger-full-access` or unset | `ON_REQUEST` / `UNLESS_TRUSTED` | existing approval loop → `tool.handle()` |
   | `PROMPT` or unset | `read-only` / `workspace-write` | `NEVER` | `tool.sandbox_execute()` → `ToolError(code="sandbox_blocked")` on denial, no prompt |
   | `PROMPT` or unset | `read-only` / `workspace-write` | `ON_FAILURE` | `tool.sandbox_execute()` → on sandbox denial, offer "retry without sandbox?" prompt |
   | `PROMPT` or unset | `read-only` / `workspace-write` | `ON_REQUEST` / `UNLESS_TRUSTED` | existing approval loop → `tool.sandbox_execute()` |

   - Preserve all M2 contracts: `ABORT` terminal, `DENIED` non-terminal.
   - Existing `ON_FAILURE` tests are unchanged — they test the no-sandbox path (`sandbox_policy=None`).
   - Value: explicit, testable decision surface; approval prompt is last resort after exec policy and sandbox both pass.
   - Verification: `pytest tests/tools/test_orchestrator.py -k "sandbox or exec_policy" -q`

4. **`ShellTool.sandbox_execute()` + `--sandbox` CLI flag**
   - Implement `ShellTool.sandbox_execute(args, cwd, policy)` using `build_sandbox_argv()`. Mirrors `handle()` — same timeout, output-cap, and error handling — only the subprocess argv changes.
   - Add `--sandbox` flag to `__main__.py` with choices from `SandboxPolicy`. Default: `danger-full-access` (no behavior change for existing users). Thread through `_build_tool_router()` → `OrchestratorConfig(sandbox_policy=...)`.
   - Value: end-to-end verifiable path from CLI flag through to subprocess wrapping.
   - Verification: `pytest tests/approval/test_sandbox_platform.py -q` + `pytest tests/tools/test_shell.py -k sandbox -q`

**Deferred (not in M5):**
- Exec policy rule files or Starlark format — hardcoded `DEFAULT_RULES` are sufficient.
- `proposed_execpolicy_amendment` — "add a rule so you're not asked again" UX; M6 candidate.
- Network approval context — not needed until network-touching tools exist.
- Windows sandbox.

**Test it**: `python -m pycodex --sandbox read-only "rm -rf /"` → blocked by exec policy or sandbox; no filesystem writes.

**Key learning**: Defense in depth requires independent layers — exec policy and sandbox enforce separately; neither bypasses the other. `ALLOW` skips the prompt but not the sandbox under restrictive policies. `danger-full-access` disables the sandbox but not the approval prompt. Fail-visible not fail-open: missing native sandbox under restrictive policy surfaces as a warning, not silent no-op. The decision matrix is the authoritative spec for orchestrator behavior.

---

### Milestone 6: Context Management + Polish

**Goal**: Token tracking, planner-driven execution, skill extensibility, web-search tool integration, auto-compaction, session persistence, configuration, and transport upgrade from stdio pipes to local server.

#### Milestone 6 execution plan (clear, incremental, verifiable)

1. **Token accounting service**
   - Add per-turn and cumulative usage tracking, surfaced to status bar and `turn.completed`.
   - Value: objective context-budget visibility.
   - Verification: `pytest tests/core/test_token_usage.py -q`

2. **Implementing planner**
   - Add a planner component that tracks explicit task steps (`pending | in_progress | completed`) and updates them as tool calls complete.
   - Surface planner state via protocol events and render it in CLI/TUI status so progress is visible during long runs.
   - Value: improves reliability for multi-step tasks by making execution intent and progress explicit.
   - Verification: `pytest tests/core/test_planner.py tests/core/test_event_adapter.py -k plan -q`

3. **Auto-compaction policy + executor**
   - Trigger near context window threshold; replace older context with deterministic summary block.
   - Value: keeps long sessions functional with bounded prompt growth.
   - Verification: `pytest tests/core/test_compaction.py -q`

4. **Session persistence and resume**
   - Persist history/config to `~/.pycodex/sessions/<id>.json`; add resume entrypoint.
   - Value: continuity across runs and recoverability after interruption.
   - Verification: `pytest tests/core/test_session_persistence.py tests/test_main.py -k resume -q`

5. **User config loading**
   - Add `~/.pycodex/config.toml` defaults and override precedence documentation/tests.
   - Value: reproducible local behavior without long CLI flags.
   - Verification: `pytest tests/core/test_config.py -k toml -q`

6. **Skills system integration**
   - Add skill discovery/loader plumbing from `$CODEX_HOME/skills` and expose selected skills to the planner/agent as explicit execution context.
   - Enforce deterministic skill resolution rules (named skill first, minimal file loading, fallback behavior when skill files are missing).
   - Value: enables reusable task-specific workflows without hardcoding behavior into core agent logic.
   - Verification: `pytest tests/core/test_skill_loader.py tests/core/test_agent.py -k skill -q`

7. **Web search tooling**
   - Add network-backed `web_search` / `web_fetch` tools with explicit domain allowlisting and approval-aware execution in the orchestrator.
   - Standardize tool outputs (title, URL, snippet, timestamp/source metadata) and include deterministic fixtures for harness tests.
   - Value: enables current-information retrieval while preserving auditability and safety boundaries.
   - Verification: `pytest tests/tools/test_web_search.py tests/tools/test_orchestrator.py -k web -q`

8. **Runtime resiliency pass**
   - Finalize retry/backoff, tool timeout boundaries, and Ctrl+C interruption behavior.
   - Value: safer long-running interactive operation.
   - Verification: `pytest tests/e2e/test_cli_tool_failures.py tests/e2e/test_interrupts.py -q`

9. **Transport upgrade: stdio pipe → WebSocket / Unix socket**
   - **Why**: The JSON-RPC envelope established in M4 is transport-agnostic by design. Upgrading the transport from stdio pipes to a local WebSocket server enables multi-client scenarios (VS Code extension, web UI, remote access) without any protocol changes.
   - **Python side**: Add `core/server.py` — `asyncio` WebSocket server (`websockets` library) that accepts connections and runs the same `TuiBridge` command-dispatch logic. Python starts listening on a Unix socket or `localhost:<port>` instead of reading from `sys.stdin`; it still emits JSONL to the socket instead of `sys.stdout`.
   - **TypeScript side**: Replace `child.stdout`/`child.stdin` pipe wiring in `index.ts` with a WebSocket client (`ws` package). `protocol/reader.ts` and `protocol/writer.ts` swap their underlying I/O from readline streams to WebSocket messages — the JSON-RPC message format is identical.
   - **Protocol is unchanged**: `user.input`, `approval.response`, `interrupt`, `approval.request`, `item.updated`, and all existing M3 events carry over without modification. No schema changes required.
   - **Multi-client path**: WebSocket server can accept multiple simultaneous clients (e.g., VS Code extension + Ink TUI); agent events are broadcast to all connected clients. Approval responses are routed by `request_id`.
   - **Pipes remain as fallback**: `--tui-mode` stdio path stays intact for environments where a local server is undesirable (CI, SSH, piped scripting).
   - Value: unlocks VS Code extension, web frontend, and remote session scenarios without touching the agent, tool, or approval logic.
   - Verification: `pytest tests/core/test_server.py -q` + `jest tui/ -k websocket -q` + manual multi-client test (two TypeScript clients connecting simultaneously).

**Test it**: Full multi-turn session with token tracking, save session, resume later; open second client (VS Code extension stub) connecting to same Python server and observing same event stream.

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
| Language | Rust + TypeScript | Python (agent) + TypeScript/React/Ink (TUI) |
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
- **M4**: `node tui/dist/index.js` (interactive) — multi-turn Ink chat with streaming text and approval modal
- **M5**: `python -m pycodex --sandbox read-only "rm -rf /"` — should block the command
- **M6**: Long conversation that triggers auto-compaction; save and resume session
