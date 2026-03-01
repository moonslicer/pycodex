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

## Build-Up Plan: 11 Incremental Milestones

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
- No event replay, persistence, or session recovery (M8).
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

**Key learning**: TypeScript/Python process boundary; JSON-RPC framing over stdio pipes; React + Ink component model; bidirectional request/response protocol with asyncio.Event suspension; transport-agnostic envelope design (pipes now, WebSocket in M11).

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
- `proposed_execpolicy_amendment` — "add a rule so you're not asked again" UX; future candidate.
- Network approval context — not needed until network-touching tools exist.
- Windows sandbox.

**Test it**: `python -m pycodex --sandbox read-only "rm -rf /"` → blocked by exec policy or sandbox; no filesystem writes.

**Key learning**: Defense in depth requires independent layers — exec policy and sandbox enforce separately; neither bypasses the other. `ALLOW` skips the prompt but not the sandbox under restrictive policies. `danger-full-access` disables the sandbox but not the approval prompt. Fail-visible not fail-open: missing native sandbox under restrictive policy surfaces as a warning, not silent no-op. The decision matrix is the authoritative spec for orchestrator behavior.

---

### Milestone 6: Instruction Context System (System Prompt + Developer Instructions)

**Goal**: Make model behavior deterministic and policy-aware by introducing a two-layer instruction system:
1. `instructions` field (base system prompt) sent on every model call.
2. One-time initial context injection (policy, project docs, environment) prepended to session history before first user turn.

**Design reference**: Informed by Codex's split between base instructions and initial context assembly (`build_initial_context()`/project docs). Extends the design with an `AgentProfile` type that separates agent identity from runtime config — making it possible to build a different agent on this framework without touching framework internals.

#### Milestone 6 execution plan (clear, incremental, verifiable)

1. **`AgentProfile` + `CODEX_PROFILE` built-in**
   - Add `core/agent_profile.py` with a frozen `AgentProfile` dataclass (`name`, `instructions`, `instruction_filenames`, `enabled_tools`) and no framework imports.
   - Add `CODEX_PROFILE` as the built-in coding assistant profile; add `load_profile_from_toml()` for custom profiles.
   - `Config` gains `profile: AgentProfile = CODEX_PROFILE` and `project_doc_max_bytes: int = 32768`. Agent identity lives in the profile, not as raw strings in `Config`.
   - Value: building a different agent means defining a new profile — no framework code changes required.
   - Verification: `pytest tests/core/test_agent_profile.py tests/core/test_config.py -q`

2. **Session support for system/developer context**
   - Add `Session.append_system_message(text)` and `Session.prepend_items(items)`.
   - Preserve Session as the sole history mutator.
   - Value: a clean, explicit API for one-time context injection.
   - Verification: `pytest tests/core/test_session.py -q`

3. **Wire `instructions` into model requests**
   - Extend `ModelClient.stream(..., instructions: str)` and pass it to Responses API `instructions`.
   - Keep initial-context system items in `input`; do not dedupe them with `instructions`.
   - Value: stable two-layer instruction behavior matching Codex architecture at pycodex scale.
   - Verification: `pytest tests/core/test_model_client.py -q`

4. **Hierarchical project-doc loader (profile-driven filenames)**
   - Add `core/project_doc.py` with git-root discovery and root→cwd instruction file concatenation.
   - `load_project_instructions(cwd, filenames, max_bytes)` — takes filenames from `config.profile.instruction_filenames`, not a hardcoded constant.
   - Cap output by `project_doc_max_bytes`; return `None` when no docs are found.
   - Value: project-specific instructions inject automatically; custom agents use their own filenames.
   - Verification: `pytest tests/core/test_project_doc.py -q`

5. **Assemble initial context in one place**
   - Add `core/initial_context.py` with `build_initial_context(config) -> list[PromptItem]`.
   - Include, in order: policy context, project docs (via `config.profile.instruction_filenames`), environment context.
   - Value: deterministic, profile-driven context assembly with one ownership point.
   - Verification: `pytest tests/core/test_initial_context.py -q`

6. **Agent and CLI wiring**
   - Prepend initial context exactly once before first turn in `core/agent.py`; pass `config.profile.instructions` to `model_client.stream()`.
   - Add `--profile`, `--profile-file`, `--instructions`, `--instructions-file` in `__main__.py`.
   - Precedence: `--instructions` > `--instructions-file` > `--profile-file` > `--profile` > config TOML > `CODEX_PROFILE`.
   - Value: user-selectable agent identity and overridable instructions without changing code.
   - Verification: `pytest tests/core/test_agent.py tests/test_main.py -k "profile or instructions or initial_context" -q`

7. **Milestone quality + smoke checks**
   - Run: `ruff check . --fix`, `ruff format .`, `mypy --strict pycodex/`, `pytest tests/ -v`.
   - Manual smoke:
     - `python -m pycodex "in one sentence, what is your role?"`
     - `python -m pycodex --instructions "You are a haiku generator." "hello"`
     - `python -m pycodex --profile-file custom.toml "what are you?"`
   - Value: ensures instruction architecture is production-safe before broader M7 work.

**Test it**: Create a repo-level `AGENTS.md` and run a prompt — behavior reflects project instructions without user prompting. Then run `--profile-file` with a custom profile pointing to a different instruction filename — the correct file loads.

**Key learning**: Separating agent identity (`AgentProfile`) from runtime config (`Config`) means the same framework can run different agents. Profile-driven instruction filenames eliminate hardcoded constants from the loader. The two-layer design (base instructions + initial context) keeps prompts stable and policy visible.

---

### Milestone 7: Context Lifecycle Foundation

**Goal**: Stabilize long-running session behavior by completing the context/state core — token accounting, compaction behavior, global config, and local resiliency. Session persistence and resume are intentionally deferred to M8 (JSONL Ledger), which builds on the stable compaction output shape established here.

**Design constraint**: Items 1 and 2 have a hard ordering dependency: token accounting must exist before the compaction trigger can work. Compaction output shape (the summary block format) must be finalized here before M8 records it to JSONL.

**Non-goals**:
- No session persistence or resume — that is M8's job.
- No planner state persistence — planner state is ephemeral (M9).
- No network tool resiliency — that scope belongs to M10.
- No transport migration — deferred to M11.

#### Milestone 7 execution plan (clear, incremental, verifiable)

1. **Token accounting service** *(prerequisite for item 2)*
   - Add per-turn and cumulative input/output token tracking in `core/agent.py` and `core/model_client.py`.
   - Surface totals through `turn.completed.usage` (partially wired in M3; finalize here) and expose cumulative totals via session state.
   - Value: objective context-budget visibility; unblocks compaction trigger.
   - Verification: `pytest tests/core/test_token_usage.py -q`

2. **Auto-compaction policy + executor** *(depends on item 1)*
   - Trigger compaction when remaining context falls below a configurable threshold (default: 20% of model context window).
   - Replace older context with a deterministic summary block produced by a local summarization call.
   - Threshold controlled by new `Config` field: `compaction_threshold_ratio: float = 0.2`.
   - Finalize the summary block format here — M8 will persist `compaction.applied` records containing this format; it must not change after M8 ships.
   - Value: keeps long sessions functional with bounded prompt growth; establishes the stable output contract M8 depends on.
   - Verification: `pytest tests/core/test_compaction.py -q`

3. **Global user config (`~/.pycodex/config.toml`)**
   - Add discovery and loading of `~/.pycodex/config.toml` as the global defaults layer.
   - New fields to support here: `compaction_threshold_ratio` (item 2), `default_approval_policy`, `default_sandbox_policy`. Existing fields (`model`, `profile`) also settable globally.
   - Precedence: CLI flags > env vars > project `pycodex.toml` > `~/.pycodex/config.toml` > hardcoded defaults.
   - Value: reproducible local behavior without long CLI flags.
   - Verification: `pytest tests/core/test_config.py -k global_config -q`

4. **Local resiliency pass** *(scope: subprocess and shell tool failures only — network resiliency is M10)*
   - Finalize retry/backoff for transient model API errors (partially done in M1; harden edge cases).
   - Add explicit timeout handling for shell tool subprocess hangs beyond the configured limit.
   - Verify clean Ctrl+C interruption of active turns in text mode and JSON mode (non-TUI paths).
   - Value: reliable single-client operation before adding complexity in M8+.
   - Verification: `pytest tests/e2e/test_cli_tool_failures.py tests/e2e/test_interrupts.py -q`

**Test it**: Run a long multi-turn session until compaction triggers and confirm the summary block replaces older context correctly; verify token totals in `turn.completed.usage`; verify Ctrl+C exits cleanly.

**Key learning**: Token accounting and compaction are prerequisites for persistence — the ledger in M8 records what happened, not what to compute. Finalizing the compaction output format here prevents M8 from inheriting an unstable contract.

---

### Milestone 8: JSONL Session Ledger + Resume

**Goal**: Establish one durable, append-only JSONL persistence system for session state and replay so resume, recovery, list, and archive are all built on one stable contract before planner, network, or transport features add their own session items.

**Design decisions**:
- **Append-only JSONL** — simple, grep-able, no ORM. SQLite is deferred and optional (index-only if added later).
- **Single-writer recorder** — one async task owns all writes via a queue; prevents interleaved/corrupt lines.
- **Flat file layout** — `~/.pycodex/sessions/rollout-YYYYMMDD-<timestamp>-<thread_id>.jsonl`. Date prefix keeps files sortable without nested `YYYY/MM/DD` subdirectories.
- **`schema_version` mismatch policy**: unknown record types are soft-skipped with a warning (forward-compatibility for future milestones); mismatched major version hard-fails the resume with an explicit error. This decision is locked in here and must not be revisited silently.
- **Close summary in `session.closed`** — `session.closed` stores last user message, turn count, final token total, and closed timestamp so `session read` is a single-record lookup when the session ended cleanly.

**Non-goals**:
- No planner state persistence — planner state is ephemeral (M9).
- No web result caching or network resiliency changes.
- No transport or server changes.
- No SQLite in this milestone (optional later as index only).
- No redesign of compaction algorithm — only its persisted representation (`compaction.applied` record).

#### Milestone 8 execution plan (clear, incremental, verifiable)

1. **Rollout schema contract**
   - Define `RolloutItem` union with `schema_version` on every record.
   - Required record types: `session.meta`, `history.item`, `turn.completed`, `compaction.applied`, `session.closed`.
   - `session.meta` at open carries profile name, model, cwd, and open timestamp. `session.closed` carries close summary fields for fast `session read` without full replay.
   - Guarantee append-only semantics and deterministic replay ordering.
   - Value: stable wire contract that all downstream milestones write against.
   - Verification: `pytest tests/core/test_rollout_schema.py -q` (including golden fixture for each record type)

2. **JSONL recorder service**
   - Add `core/rollout_recorder.py` — single-writer async recorder with queue-based ingestion.
   - Public API: `record(items)`, `flush()`, `shutdown()`.
   - Recorder is owned by the session (not a global singleton); multiple sessions have independent recorders.
   - Value: safe, non-blocking persistence with no risk of interleaved writes.
   - Verification: `pytest tests/core/test_rollout_recorder.py -q`

3. **Filesystem layout**
   - Path: `~/.pycodex/sessions/rollout-YYYYMMDD-<timestamp>-<thread_id>.jsonl`
   - Archive path: `~/.pycodex/archived_sessions/rollout-...jsonl` (same filename, different root).
   - `thread_id` is the canonical session identifier; latest rollout for a given `thread_id` is resolved by filename sort.
   - Value: flat, glob-friendly layout; no nested year/month/day traversal required.
   - Verification: path resolution unit tests in `test_rollout_recorder.py`

4. **Wire persistence write points**
   - Persist `session.meta` at session creation.
   - Persist `history.item` records after each successful turn mutation (user message, assistant message, tool call, tool result).
   - Persist `turn.completed` with per-turn and cumulative token snapshot from M7.
   - Persist `compaction.applied` with the summary block and replaced item range when compaction runs.
   - Persist `session.closed` on clean shutdown.
   - Value: every durable state change has a corresponding ledger record.
   - Verification: `pytest tests/core/test_rollout_recorder.py -k write_points -q`

5. **Replay engine**
   - Read JSONL in order; validate `schema_version` on each record.
   - Unknown record types: soft-skip with warning (forward-compat). Major version mismatch: hard-fail with explicit error.
   - Reconstruct session history and config snapshot from ledger.
   - Rebuild token totals from persisted `turn.completed` records — no hidden recomputation.
   - Tolerate truncated last line (crash recovery): replay up to the last valid complete record.
   - If `session.closed` is absent, treat the rollout as uncleanly terminated; replay to last valid record and mark state as `incomplete`.
   - Value: deterministic reconstruction from ledger alone; no dependency on planner/network/transport.
   - Verification: `pytest tests/core/test_rollout_replay.py -q`

6. **Resume entrypoint**
   - `--resume <thread-id|rollout-path>` in `__main__.py`.
   - Resolve latest rollout by `thread_id` if only an ID is provided.
   - Start session from replayed state and continue with normal turn loop.
   - Value: continuity across runs and recoverability after interruption.
   - Verification: `pytest tests/test_main.py -k resume -q`

7. **Session lifecycle commands (`session` subcommand)**
   - `session list` — newest-first from rollout files; shows thread_id, date, turn count, token total, and status (`closed` | `incomplete`).
   - `session read <id>` — use `session.closed` summary when present; otherwise replay and return best-effort summary with `status: "incomplete"`.
   - `session archive <id>` — moves rollout file to `~/.pycodex/archived_sessions/`; no content rewrite.
   - `session unarchive <id>` — moves back to `~/.pycodex/sessions/`.
   - Value: observable, manageable session history.
   - Verification: `pytest tests/e2e/test_session_archive.py -q`

8. **Durability and failure behavior**
   - Force `flush()` at turn boundaries and on clean shutdown.
   - Crash recovery: on restart, replay tolerates truncated last line; resumes from last valid record.
   - Explicit error codes: `rollout_not_found`, `schema_version_mismatch`, `replay_failure`.
   - Value: safe recovery without silent data loss.
   - Verification: `pytest tests/e2e/test_session_resume.py -k crash -q`

9. **Back-compat bridge for legacy `.json` sessions**
   - One-time import: if `~/.pycodex/sessions/<id>.json` exists, convert to rollout JSONL on first `--resume`.
   - Mark imported sessions with `session.meta.import_source = "legacy_json"`.
   - Importer is idempotent — re-running does not create duplicate rollout files.
   - Value: users with M7-era sessions can resume without manual migration.
   - Verification: `pytest tests/core/test_rollout_legacy_import.py -q`

10. **Test and contract lock-in**
    - Unit tests: recorder, replay, schema validation, path resolution.
    - E2E tests: save/resume, crash recovery, archive/unarchive, legacy import.
    - Golden JSONL fixtures for each record type — CI fails if fixture output changes, preventing accidental schema drift.
    - Verification: `pytest tests/core/test_rollout_schema.py tests/core/test_rollout_recorder.py tests/core/test_rollout_replay.py tests/e2e/test_session_resume.py tests/e2e/test_session_archive.py -q`

**Test it**: Run a multi-turn session; `session list` shows it; `--resume <id>` continues it. Kill the process mid-write; `--resume` recovers cleanly through the last flushed turn. `session archive <id>` moves it; `session unarchive <id>` restores it.

**Key learning**: An append-only ledger is simpler to reason about than a mutable snapshot: replay is just reading forward, crash recovery is just stopping at the last valid line, and schema evolution is just soft-skipping unknown records. All future milestones write session items against this one stable contract.

---

### Milestone 9: Agent Guidance Layer (Planner + Skills)

**Goal**: Add visible planning/progress and skill extensibility on top of the stable session foundation from M7–M8.

**Design constraints**:
- Planner is a **guidance layer, not an execution controller** — it tracks and signals state, it does not gate tool dispatch.
- Planner state is **ephemeral** — not persisted to `~/.pycodex/sessions/`. A resumed session starts with no active plan. This keeps the M8 session persistence format stable.
- Skills are discovered once at session start; no hot-reload.

#### Milestone 9 execution plan (clear, incremental, verifiable)

1. **Planner as state/progress signaling**
   - Implement explicit step state (`pending | in_progress | completed`) updated as tool calls complete.
   - Planner state is ephemeral: not included in session persistence from M8.
   - Value: makes execution intent and progress visible without introducing hidden control flow.
   - Verification: `pytest tests/core/test_planner.py -q`

2. **Plan rendering + protocol consistency**
   - Emit plan state changes as protocol events; render in text mode, JSON mode, and TUI status bar.
   - Ensure plan updates are consistent across all three output modes before shipping.
   - Value: plan state is a first-class observable, not a debug artifact.
   - Verification: `pytest tests/protocol/test_events.py tests/core/test_event_adapter.py -k plan -q`

3. **Skills discovery, resolution, and guardrails**
   - Load skills from configured roots (`$CODEX_HOME/skills` or `~/.pycodex/skills/`).
   - Enforce deterministic selection: named skill first, explicit fallback when skill files are missing or invalid.
   - Validate edge cases: missing file, disabled skill, malformed skill — all produce clear errors, not silent no-ops.
   - Inject selected skill context into agent initial context via `build_initial_context()` from M6.
   - Value: reusable task-specific workflows without hardcoding behavior into core agent logic.
   - Verification: `pytest tests/core/test_skill_loader.py tests/core/test_agent.py -k skill -q`

**Test it**: Use a task that names a skill and requires multi-step execution; confirm visible plan state transitions and deterministic skill selection behavior (including missing-skill error path).

**Key learning**: Planning and skills improve execution quality only when they remain explicit guidance layers. Planner state being ephemeral is a deliberate simplification that keeps session persistence stable across milestones.

---

### Milestone 10: Web Tooling + Network Safety

**Goal**: Introduce web retrieval with strict safety constraints and deterministic outputs, without changing transport architecture.

**Scope decision**: M10 ships `web_search` only. `web_fetch` (arbitrary page content retrieval) is deferred — it carries a larger attack surface, higher prompt-injection risk, and requires separate approval semantics. Revisit after M10 is stable.

**Prompt injection defense**: Web search results are untrusted external content. Results must be delivered to the model wrapped in a structured delimiter (e.g., `[web_search result: <url>] ... [/web_search result]`) so they are visually and semantically distinct from developer instructions. The base system prompt (from M6) must include a standing instruction that tool results from web searches are untrusted and may contain adversarial content.

**Non-goals**:
- No `web_fetch` in this milestone.
- No cached web mode — insufficient value without a stable cache store.
- No transport or multi-client changes.

#### Milestone 10 execution plan (clear, incremental, verifiable)

1. **`web_search` tool**
   - Add `tools/web_search.py` with normalized output schema: `title`, `url`, `snippet`, `retrieved_at`.
   - Results wrapped in structured delimiter block before being returned to the model (prompt injection defense).
   - Include deterministic fixtures for unit tests — no live network calls in the test suite.
   - Value: current-information retrieval with auditable, structured output.
   - Verification: `pytest tests/tools/test_web_search.py -q`

2. **Approval-aware network execution**
   - Route `web_search` through existing orchestrator approval policies.
   - Add optional domain allowlist: requests to non-allowlisted domains return `ToolError(code="domain_not_allowed")`.
   - Value: web tool inherits existing safety boundaries; allowlist constrains blast radius.
   - Verification: `pytest tests/tools/test_orchestrator.py -k web -q`

3. **Web mode + config gating**
   - Add `web_search_mode: Literal["disabled", "live"] = "disabled"` to `Config`.
   - `disabled` (default): tool returns `ToolError(code="web_search_disabled")` without making network calls.
   - `live`: makes real search requests.
   - Value: safe default; explicit opt-in for any network access.
   - Verification: `pytest tests/core/test_config.py -k web_search -q`

4. **Network resiliency for web tools** *(scope: network-specific failures only — local tool resiliency was M7)*
   - Harden retry/backoff/timeout specifically for `web_search` HTTP calls.
   - Ensure timeout, DNS failure, and HTTP error surfaces produce structured `ToolError` with actionable codes, not raw exceptions.
   - Value: auditable failure surfaces for network-backed tools.
   - Verification: `pytest tests/e2e/test_cli_tool_failures.py -k web -q`

**Test it**: Ask for current information with `web_search_mode=disabled` (blocked), then `live` (returns results); verify approval prompt appears under `on-request` policy; verify domain allowlist blocks off-list domains.

**Key learning**: Network tools must be introduced as constrained, policy-first capabilities. Untrusted content delimitation is not optional — it is the primary defense against prompt injection from web results.

---

### Milestone 11: Transport Upgrade + Multi-Client Runtime

**Goal**: Move from stdio-only interaction to an optional local WebSocket transport with correct event broadcast, approval routing, and interruption semantics across multiple clients.

**Protocol decision**: Python server uses `asyncio` WebSocket (`websockets` library) on `localhost:<port>` with an optional Unix socket path. The JSON-RPC envelope from M4 is unchanged. TypeScript switches to a `ws` package client; `protocol/reader.ts` and `protocol/writer.ts` swap their I/O layer only — message format is identical. The `--tui-mode` stdio path remains as a fallback for CI, SSH, and pipe-scripting environments.

**Session affinity**: One active turn per session at a time. A second client connecting to an active session receives the event stream as a read-only observer but cannot start a new turn until the current one completes. Concurrent turn attempts return a structured error (`{"error": "turn_in_progress"}`). This constraint keeps approval and interrupt routing unambiguous.

**Non-goals**:
- No multi-agent sessions (multiple independent agents on one server).
- No remote (non-localhost) server exposure.
- No authentication on the local socket.

#### Milestone 11 execution plan (clear, incremental, verifiable)

1. **Server transport layer** *(asyncio WebSocket, `websockets` library, `localhost:<port>` + optional Unix socket)*
   - Add `core/server.py` with WebSocket server that reuses `TuiBridge` command-dispatch logic from M4.
   - Enforce single-active-turn constraint: new turn requests while a turn is active return `{"error": "turn_in_progress"}`.
   - Value: transport-agnostic agent core; opens path to VS Code extension and web UI.
   - Verification: `pytest tests/core/test_server.py -q`

2. **TypeScript client transport adapter**
   - Replace `child.stdout`/`child.stdin` pipe wiring in `index.ts` with a WebSocket client (`ws` package).
   - `protocol/reader.ts` and `protocol/writer.ts` swap I/O from readline streams to WebSocket messages — JSON-RPC format unchanged.
   - Keep `--tui-mode` stdio path intact as fallback.
   - Value: full roundtrip through new transport; existing protocol contract verified end-to-end.
   - Verification: `jest tui/ -k websocket -q`

3. **Multi-client event broadcast**
   - All connected clients receive the same turn/item events for the active session.
   - A client connecting mid-turn receives buffered events from the current turn's start.
   - Value: consistent observable state across all connected clients.
   - Verification: `pytest tests/core/test_server.py -k broadcast -q`

4. **Approval and interrupt routing across clients**
   - Approval requests (`approval.request`) are broadcast to all clients; the first `approval.response` with a matching `request_id` wins — subsequent responses for the same ID are ignored.
   - Interrupt commands from any client cancel the active turn for all clients.
   - Value: approval and interruption remain reliable and unambiguous in multi-client sessions.
   - Verification: `pytest tests/core/test_tui_bridge.py -k "approval or interrupt" -q` + `pytest tests/core/test_server.py -k routing -q`

5. **Transport-level resiliency**
   - Handle client disconnect mid-turn gracefully: turn continues; reconnecting client receives buffered events from turn start.
   - Add backpressure handling for slow clients (bounded event queue; drop or block on overflow).
   - Value: stable multi-client operation under realistic network and process conditions.
   - Verification: `pytest tests/core/test_server.py -k "reconnect or backpressure" -q`

**Test it**: Connect two clients to one active session; confirm both observe consistent event streams; have one client approve a tool call and verify the other sees the resolution; Ctrl+C from one client cancels the turn for both.

**Key learning**: Transport evolution is a runtime-system milestone, not a feature milestone. Single-turn-per-session affinity is the constraint that keeps approval and interrupt routing tractable in a multi-client setup.

---

## Key Codex Source Files to Study

| Python Module | Codex Reference File | What to Learn |
|---|---|---|
| `core/agent_profile.py` | `codex-rs/protocol/src/openai_models.rs` (lines 282-300) | Agent identity separate from runtime config; default instructions |
| `core/agent.py` | `codex-rs/core/src/codex.rs` (lines ~4744-6370) | Agent loop, sampling request, tool dispatch |
| `core/project_doc.py` | `codex-rs/core/src/project_doc.rs` (lines 74-126) | Hierarchical instruction file discovery |
| `core/initial_context.py` | `codex-rs/core/src/codex.rs` (lines 2977-3058) | Initial context assembly order and sources |
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
| Skills/hooks | Full skill system, lifecycle hooks | Simplified loader + deterministic resolution (M9) |
| Web fetch | Full web_fetch + MITM proxy | `web_search` only (M10); `web_fetch` deferred |

## Verification Plan

After each milestone, verify with these tests:

- **M1**: `python -m pycodex "list files in current directory and show me the contents of pyproject.toml"` — model should call shell/read_file tools and return results
- **M2**: `python -m pycodex --approval on-request "create a file called test.txt with 'hello'"` — should prompt before writing
- **M3**: `python -m pycodex --json "what is 2+2"` — should emit valid JSONL events
- **M4**: `node tui/dist/index.js` (interactive) — multi-turn Ink chat with streaming text and approval modal
- **M5**: `python -m pycodex --sandbox read-only "rm -rf /"` — should block the command
- **M6**: `python -m pycodex "What is your role?"` — default `CODEX_PROFILE` identity; `python -m pycodex --profile-file custom.toml "what are you?"` — custom profile loads; `AGENTS.md` in project tree injects automatically
- **M7**: Run a long multi-turn session until compaction triggers; confirm the summary block replaces older context correctly; verify token totals in `turn.completed.usage`; verify Ctrl+C exits cleanly (no `--resume` yet — that is M8)
- **M8**: Run a multi-turn session; `session list` shows it; `--resume <id>` continues it; kill the process mid-write and recover cleanly from the last valid turn; `session archive <id>` / `session unarchive <id>` roundtrip succeeds
- **M9**: Task that names a skill and requires multi-step execution — visible plan state transitions, deterministic skill selection, clear error on missing skill
- **M10**: `web_search_mode=live` query returns structured results; `disabled` (default) blocks without network calls; domain allowlist rejects off-list requests
- **M11**: Two clients connected to one session — both observe consistent event stream; approval from one client resolves for both; Ctrl+C from either client cancels the active turn
