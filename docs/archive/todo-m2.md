# Milestone 2 TODO - Permission System + More Tools

## Goal
Extend `python -m pycodex "<prompt>"` with:
1. approval gating before mutating tool calls,
2. session-scoped approval caching,
3. three new tools: `write_file`, `list_dir`, `grep_files`,
4. `--approval` CLI flag to control policy.

## In Scope
- `pycodex/approval/policy.py`
- `pycodex/tools/orchestrator.py`
- `pycodex/tools/write_file.py`
- `pycodex/tools/list_dir.py`
- `pycodex/tools/grep_files.py`
- `pycodex/tools/base.py` (modify: add optional `OrchestratorConfig` to `ToolRegistry`)
- `pycodex/__main__.py` (modify: add `--approval` flag + orchestrator wiring)
- `tests/approval/test_policy.py`
- `tests/tools/test_orchestrator.py`
- `tests/tools/test_write_file.py`
- `tests/tools/test_list_dir.py`
- `tests/tools/test_grep_files.py`

## Out of Scope
- Sandboxing (M5)
- `ON_FAILURE` escalation retry (M5 — behaves as `NEVER` in M2)
- Interactive TUI approval modal (M4)
- `exec_policy.py` command-prefix rules (M5)
- JSONL event protocol (M3)

## Success Metrics

### Functional
- `python3 -m pycodex --approval on-request "create a hello.py"` prompts before writing.
- `python3 -m pycodex --approval never "create a hello.py"` writes without prompting.
- `APPROVED_FOR_SESSION` skips prompt on second identical call within the same run.
- `DENIED` returns a clean error to the model; turn continues.
- `ABORT` stops the turn with a clear message.
- `list_dir` and `grep_files` never prompt (read-only).

### Architecture/Contract
- Approval logic is stateless except through `ApprovalStore` — no module-level mutable state.
- `ApprovalStore` cache keys are `json.dumps(key, sort_keys=True)` — deterministic and order-independent.
- `APPROVED_FOR_SESSION` decisions are cached; `APPROVED` decisions are not.
- `ask_user_fn` is always injected — never hardcoded `input()` in orchestrator or policy code.
- Read-only tools bypass approval entirely — orchestrator checks `is_mutating()` first.
- `ToolAborted` exception propagates out of `execute_with_approval()`; agent loop catches it.
- `DENIED` → returns `ToolError(code="denied")` — does not raise.
- `write_file` approval key = resolved absolute path (not full args dict).
- `shell` approval key = canonicalized shell wrapper key + timeout (normalizes wrapper forms like `/bin/bash -lc` vs `bash -lc`; preserves semantically sensitive inline forms).
- Atomic write: `.tmp` sibling → `os.replace()`.
- `write_file` enforces workspace-containment (same as `read_file`).
- `grep_files` uses `rg` if available, falls back to `grep -rl`.

### Quality Gates
- `ruff check . --fix`
- `ruff format .`
- `mypy --strict pycodex/`
- `pytest tests/ -v`

### Milestone Verification
- `python3 -m pycodex --approval on-request "create a file called test.txt with 'hello'"`

## Vertical Verifiable Flow (Thin Slice)
1. CLI parses `--approval on-request`, builds `ApprovalStore` + `ask_user_fn`.
2. `OrchestratorConfig` passed into `ToolRegistry`.
3. Agent calls `write_file` → `ToolRegistry.dispatch()` → `execute_with_approval()`.
4. Orchestrator checks `is_mutating()` → `True`.
5. Cache miss → `ask_user_fn` called (non-blocking via `asyncio.to_thread`).
6. User enters `y` → `APPROVED` → file written atomically.
7. `ToolResult` serialized and appended to session.
8. Second call to same file path with `APPROVED_FOR_SESSION` → cache hit → no prompt.

## TODO Tasks (Dependency-Flexible DAG)

- [x] T1: `approval/policy.py`
  - Implement `ApprovalPolicy` enum, `ReviewDecision` enum, `ApprovalStore` with JSON-key cache + `prompt_lock`.
  - `APPROVED_FOR_SESSION` cached; `APPROVED` not cached.
  - Verify: `python3 -c "from pycodex.approval.policy import ApprovalPolicy, ReviewDecision, ApprovalStore; s=ApprovalStore(); s.put({'tool':'shell','cmd':'ls'}, ReviewDecision.APPROVED_FOR_SESSION); print(s.get({'cmd':'ls','tool':'shell'}))"`

- [x] T2: `tools/orchestrator.py`
  - Implement `execute_with_approval()`, `ToolAborted`, `OrchestratorConfig`, `AskUserFn`.
  - Read-only bypass, NEVER/ON_FAILURE auto-approve, APPROVED_FOR_SESSION cache hit, DENIED → ToolError, ABORT → ToolAborted.
  - Depends on: T1
  - Verify: `python3 -c "from pycodex.tools.orchestrator import execute_with_approval, ToolAborted, OrchestratorConfig; print('ok')"`

- [x] T3: `tools/write_file.py`
  - Atomic workspace-contained file writer. Approval key = resolved abs path.
  - Args: `file_path`, `content`. Returns `ToolResult(body={"path":…,"bytes_written":…})`.
  - `is_mutating() = True`.
  - Verify: `python3 -c "import asyncio; from pathlib import Path; from pycodex.tools.write_file import WriteFileTool; import tempfile, os; d=tempfile.mkdtemp(); r=asyncio.run(WriteFileTool().handle({'file_path':'t.txt','content':'hi'}, Path(d))); print(r)"`

- [x] T4: `tools/list_dir.py`
  - Paginated, depth-limited tree listing. `is_mutating() = False`.
  - Args: `dir_path`, `offset=1`, `limit=25`, `depth=2`. Returns `ToolResult(body=str)`.
  - Dir `/` suffix, symlink `@` suffix, 2-space indent per depth, "… N more entries" pagination.
  - Verify: `python3 -c "import asyncio; from pathlib import Path; from pycodex.tools.list_dir import ListDirTool; print(asyncio.run(ListDirTool().handle({'dir_path':'.'}, Path('.'))))"`

- [x] T5: `tools/grep_files.py`
  - rg/grep content search returning file paths sorted by mtime. `is_mutating() = False`.
  - Args: `pattern`, `path=None`, `include=None`, `limit=100`. Max limit 2000.
  - rg command: `rg --files-with-matches --sortr=modified --regexp <pattern> [--glob <include>] -- <path>`
  - Timeout 30s; exit code 1 = no matches (not an error). Falls back to `grep -rl` if no `rg`.
  - Returns `ToolResult(body={"matches":[…],"truncated":bool})`.
  - Verify: `python3 -c "import asyncio; from pathlib import Path; from pycodex.tools.grep_files import GrepFilesTool; print(asyncio.run(GrepFilesTool().handle({'pattern':'def ','path':'.'}, Path('.'))))"`

- [x] T6: `tools/base.py` (modify)
  - Add optional `orchestrator: OrchestratorConfig | None = None` to `ToolRegistry.__init__()`.
  - In `ToolRegistry.dispatch()`: if orchestrator config present, route mutating calls through `execute_with_approval()`; preserve `ToolAborted` as control flow so `core/agent.py` stops the active turn.
  - Depends on: T2
  - Verify: `python3 -c "from pycodex.tools.base import ToolRegistry; r=ToolRegistry(); print(r.tool_specs())"`

- [x] T7: `__main__.py` (modify)
  - Add `--approval {never,on-failure,on-request,unless-trusted}` arg (default: `never`).
  - Build `ApprovalStore` + non-interactive `ask_user_fn` via `asyncio.to_thread(input, prompt)`.
  - Register `WriteFileTool`, `ListDirTool`, `GrepFilesTool` in `_build_tool_router()`.
  - Pass `OrchestratorConfig` into `ToolRegistry`.
  - Depends on: T1, T2, T3, T4, T5, T6
  - Verify: `python3 -m pycodex --help` (shows `--approval`)

- [x] T8: `tests/approval/test_policy.py`
  - Unit tests: `ApprovalStore` get/put, key normalization (dict order independence), `APPROVED_FOR_SESSION` cached, `APPROVED` not cached, `prompt_lock` is asyncio.Lock.
  - Depends on: T1
  - Verify: `pytest tests/approval/test_policy.py -v`

- [x] T9: `tests/tools/test_orchestrator.py`
  - Unit tests with mock `ask_user_fn` (never use `policy=NEVER` to hide approval path):
    - read-only tool bypasses approval entirely
    - `NEVER` policy auto-approves without calling `ask_user_fn`
    - `ON_FAILURE` policy auto-approves without calling `ask_user_fn`
    - `APPROVED_FOR_SESSION` cache hit skips `ask_user_fn`
    - `ON_REQUEST` + `APPROVED` calls `ask_user_fn`, executes tool, does NOT cache
    - `ON_REQUEST` + `APPROVED_FOR_SESSION` calls `ask_user_fn`, executes tool, caches key
    - `DENIED` returns `ToolError(code="denied")`, does not raise
    - `ABORT` raises `ToolAborted`
  - Depends on: T2
  - Verify: `pytest tests/tools/test_orchestrator.py -v`

- [x] T10: `tests/tools/test_write_file.py`
  - Unit tests: success write + correct bytes_written, atomic rename (tmp file cleaned up), workspace escape rejected, missing parent dir created, existing file overwritten.
  - Depends on: T3
  - Verify: `pytest tests/tools/test_write_file.py -v`

- [x] T11: `tests/tools/test_list_dir.py`
  - Unit tests: basic listing, depth=1 limit, offset/limit pagination, dir `/` suffix, symlink `@` suffix, "… N more entries" message, nonexistent path → ToolError.
  - Depends on: T4
  - Verify: `pytest tests/tools/test_list_dir.py -v`

- [x] T12: `tests/tools/test_grep_files.py`
  - Unit tests with subprocess mocking: matches found, exit 1 = empty (no error), limit truncation sets `truncated=True`, `include` glob passed through, rg fallback to grep, timeout → ToolError.
  - Depends on: T5
  - Verify: `pytest tests/tools/test_grep_files.py -v`

- [x] T13: Approval semantics hardening (`ABORT` + decision-key canonicalization)
  - Resolve and enforce a single `ABORT` contract end-to-end:
    - User choosing `ABORT` must stop the active turn immediately (no further model/tool work in that turn).
    - Align implementation and docs across `tools/orchestrator.py`, `tools/base.py`, `core/agent.py`, and this TODO.
    - Remove conflicting behavior where abort is converted into a normal tool error continuation path.
  - Add shell approval-key canonicalization for session cache stability:
    - Normalize equivalent shell wrappers/argv forms to the same approval key (for example `/bin/bash -lc "ls -la"` vs `bash -lc "ls   -la"`).
    - Keep `write_file` key behavior unchanged (resolved absolute path).
  - Add deterministic regression tests:
    - `ABORT` path proves turn termination behavior.
    - Canonicalized shell variants hit the same session approval cache key.
  - Depends on: T2, T6, T7, T9
  - Verify: `pytest tests/tools/test_orchestrator.py -v`

## Completion Checklist
- [x] All T1–T13 done
- [x] Quality gates all pass (`ruff check`, `ruff format`, `mypy --strict`, `pytest tests/ -v`)
- [ ] Milestone verification command passes
- [x] Milestone report includes: files changed, gate results, verification output, risks/assumptions, next milestone recommendation

## Milestone 2 Holistic Report (2026-02-27)

### Milestone
- Name: Milestone 2 — Permission System + More Tools
- Overall status: Functionally complete; one manual verification command remains blocked by local runtime dependency setup.

### Files changed (M2 scope)
- `pycodex/approval/policy.py`
- `pycodex/tools/orchestrator.py`
- `pycodex/tools/write_file.py`
- `pycodex/tools/list_dir.py`
- `pycodex/tools/grep_files.py`
- `pycodex/tools/base.py`
- `pycodex/tools/shell.py`
- `pycodex/core/agent.py`
- `pycodex/__main__.py`
- `tests/approval/test_policy.py`
- `tests/tools/test_orchestrator.py`
- `tests/tools/test_write_file.py`
- `tests/tools/test_list_dir.py`
- `tests/tools/test_grep_files.py`
- `tests/tools/test_shell.py`
- `tests/core/test_agent.py`
- `tests/test_main.py`
- `todo-m2.md`

### Gate results
- `ruff check . --fix` — PASS
- `ruff format .` — PASS
- `mypy --strict pycodex/` — PASS (`Success: no issues found in 18 source files`)
- `pytest tests/ -v` — PASS (`141 passed, 1 skipped`; skip: live OpenAI e2e unreachable in this environment)

### Milestone verification command
- Command: `python3 -m pycodex --approval on-request "create a file called test.txt with 'hello'"`
- Result: BLOCKED in local runtime
- Output: `[ERROR] Failed to initialize OpenAI client: openai package is required; install openai>=1.0 to use ModelClient`

### Risks / assumptions
- `ABORT` is now explicit terminal turn control flow: orchestrator raises `ToolAborted`, registry propagates, agent terminates active turn.
- Shell approval-key canonicalization is intentionally conservative:
  - canonicalizes equivalent wrapper forms (for example `/bin/bash -lc` vs `bash -lc`)
  - normalizes whitespace only for a strict safe token subset
  - preserves semantically sensitive inline shell forms as distinct keys

### Next milestone recommendation
- Proceed to Milestone 3 (Event Protocol + JSONL Mode) after local runtime setup supports the manual milestone verification command (`openai` install + reachable endpoint where required).
