# Milestone 5 TODO — Sandboxing + Command Safety

## Goal
Add defense-in-depth for shell command execution:
1. deterministic command classification in `approval/exec_policy.py` (`ALLOW | PROMPT | FORBIDDEN`) using a canonicalized prefix-rule matcher,
2. sandbox policy domain in `approval/sandbox.py` (`danger-full-access | read-only | workspace-write`) with platform-native adapters and fail-visible unavailability,
3. orchestrator wiring in `tools/orchestrator.py` — two new optional `OrchestratorConfig` fields and the decision matrix as the authoritative dispatch table,
4. `ShellTool.sandbox_execute()` + `--sandbox` CLI flag for end-to-end verification.

## Architecture
```
__main__.py              --sandbox flag → OrchestratorConfig(sandbox_policy=…)
        ↓
tools/orchestrator.py    decision matrix: exec_policy → sandbox → approval prompt
        ↓                                ↑               ↑
approval/exec_policy.py  classify(canonicalized_cmd)     |
approval/sandbox.py      build_sandbox_argv(cmd, policy, cwd)
        ↓
tools/shell.py           ShellTool.canonical_command()   (duck-typed, exec_policy input)
                         ShellTool.sandbox_execute()     (duck-typed, sandbox wrapper)
```

**Layer semantics**: exec policy and sandbox policy are independent, additive layers.
Neither bypasses the other:
- `ALLOW` from exec policy skips the approval prompt; sandbox still runs under restrictive policies.
- `danger-full-access` disables sandbox wrapping; approval follows `ApprovalPolicy` normally.
- Both guardrails must be explicitly opted out of, separately.

**Decision matrix** (evaluated in order, first match wins):

| exec_policy result     | sandbox_policy                | approval_policy              | Outcome |
|------------------------|-------------------------------|------------------------------|---------|
| `FORBIDDEN`            | any                           | any                          | `ToolError(code="forbidden")` — no sandbox, no prompt |
| `ALLOW`                | `danger-full-access` or unset | any                          | `tool.handle()` — sandbox disabled, prompt skipped |
| `ALLOW`                | `read-only` or `workspace-write` | any                       | `tool.sandbox_execute()` — sandbox runs, prompt skipped |
| `PROMPT` or unset      | `danger-full-access` or unset | `NEVER` / `ON_FAILURE`      | `tool.handle()` — no sandbox, no prompt (existing behavior) |
| `PROMPT` or unset      | `danger-full-access` or unset | `ON_REQUEST` / `UNLESS_TRUSTED` | existing approval loop → `tool.handle()` |
| `PROMPT` or unset      | `read-only` / `workspace-write` | `NEVER`                   | `tool.sandbox_execute()` → `ToolError(code="sandbox_blocked")` on denial, no prompt |
| `PROMPT` or unset      | `read-only` / `workspace-write` | `ON_FAILURE`              | `tool.sandbox_execute()` → on sandbox denial, offer "retry without sandbox?" prompt |
| `PROMPT` or unset      | `read-only` / `workspace-write` | `ON_REQUEST` / `UNLESS_TRUSTED` | existing approval loop → `tool.sandbox_execute()` |

## In Scope
- `pycodex/approval/exec_policy.py` (new)
- `pycodex/approval/sandbox.py` (new)
- `pycodex/tools/orchestrator.py` (modify: new `OrchestratorConfig` fields + decision matrix)
- `pycodex/tools/shell.py` (modify: add `canonical_command()` + `sandbox_execute()`)
- `pycodex/__main__.py` (modify: `--sandbox` flag)
- `tests/approval/test_exec_policy.py` (new)
- `tests/approval/test_sandbox.py` (new)
- `tests/approval/test_sandbox_platform.py` (new)
- `tests/tools/test_orchestrator.py` (extend: decision matrix coverage)
- `tests/tools/test_shell.py` (extend: `sandbox_execute` + `canonical_command`)
- `tests/test_main.py` (extend: `--sandbox` flag wiring)

## Out of Scope
- Exec policy rule files or Starlark policy format — `DEFAULT_RULES` is sufficient
- `proposed_execpolicy_amendment` — "add a rule so you're not asked again" UX (M6 candidate)
- Network approval context — not needed until network-touching tools exist
- Windows sandbox
- Parallel tool dispatch — sequential ordering unchanged
- Session persistence / compaction (M6)

## Success Metrics

### Functional
- `python -m pycodex --sandbox read-only "rm -rf /"` → blocked by exec policy (`FORBIDDEN`) or `ToolError(code="sandbox_blocked")`; no filesystem writes.
- `python -m pycodex --sandbox danger-full-access "ls ."` → runs normally; approval still follows `--approval` flag.
- A command classified `ALLOW` by exec policy skips the prompt but the sandbox still wraps it under `--sandbox read-only`.
- A command classified `FORBIDDEN` returns an error immediately with no sandbox run and no approval prompt.
- Under `--sandbox read-only` with no native sandbox available, a clear warning is printed to stderr; execution does not silently proceed as if protected.
- All existing `--approval` modes work unchanged when `--sandbox` is omitted (default `danger-full-access`).

### Architecture / Contract
- `exec_policy_fn` and `sandbox_policy` are optional on `OrchestratorConfig`; all existing construction sites compile without changes.
- `ShellTool.canonical_command(args)` and `ShellTool.sandbox_execute(args, cwd, policy)` are optional duck-typed methods — not added to `ToolHandler` protocol.
- `classify()` is a pure function: no I/O, no imports from `tools/` or `core/`.
- Exec policy classification uses the canonicalized command string (same normalization as `_canonicalize_command_for_approval` in `shell.py`).
- `SandboxUnavailable` is raised (not silently swallowed) when a restrictive sandbox policy is active and no native adapter is found.
- All M2 contracts preserved: `ABORT` terminal, `DENIED` non-terminal, `ToolAborted` propagates.
- Existing `ON_FAILURE` tests (no-sandbox path) pass unchanged.

### Quality Gates
- `ruff check . --fix`
- `ruff format .`
- `mypy --strict pycodex/`
- `pytest tests/ -v`

### Milestone Verification
- `python -m pycodex --sandbox read-only --approval on-request "rm -rf /"` → blocked (exec policy `FORBIDDEN`) before prompt is shown.
- `python -m pycodex --sandbox workspace-write --approval on-request "echo hello"` → sandbox wraps command; approval prompt appears.

## Vertical Verifiable Flow (Thin Slice)
1. User runs `python -m pycodex --sandbox read-only "rm -rf /"`.
2. `__main__.py` parses `--sandbox read-only` → `OrchestratorConfig(sandbox_policy=SandboxPolicy.READ_ONLY)`.
3. Agent calls `shell` tool with `args={"command": "rm -rf /"}`.
4. Orchestrator calls `ShellTool.canonical_command(args)` → `"rm -rf /"`.
5. `exec_policy_fn("rm -rf /")` matches `DEFAULT_RULES` prefix → `ExecDecision.FORBIDDEN`.
6. Orchestrator returns `ToolError(code="forbidden")` — no subprocess spawned, no prompt shown.
7. Model receives tool error, reports it in final text.

## TODO Tasks

- [ ] T1: `approval/exec_policy.py` — ExecDecision enum + classify() + DEFAULT_RULES + default_heuristics
  - Define `ExecDecision(StrEnum)` with values `ALLOW = "allow"`, `PROMPT = "prompt"`, `FORBIDDEN = "forbidden"`.
  - Implement `classify(command: str, rules: list[tuple[str, ExecDecision]], heuristics: Callable[[str], ExecDecision] | None = None) -> ExecDecision`:
    - `command` is the pre-canonicalized command string (caller's responsibility).
    - Iterate `rules` in order; if `command` starts with the prefix (after stripping leading whitespace), return that `ExecDecision`. First match wins.
    - If no rule matches: call `heuristics(command)` if provided, else return `PROMPT`.
  - Export `DEFAULT_RULES: list[tuple[str, ExecDecision]]` — a sensible baseline covering the most impactful cases (e.g. `"rm -rf /"` → `FORBIDDEN`, `"rm -rf ~"` → `FORBIDDEN`, `"ls"` / `"cat"` / `"echo"` / `"pwd"` / `"which"` / `"env"` → `ALLOW`; all others implicitly `PROMPT` via heuristics).
  - Export `default_heuristics(command: str) -> ExecDecision` — returns `PROMPT` for anything not covered by rules; can be extended later.
  - Module has zero imports from `tools/`, `core/`, or `approval/policy.py`.
  - Tests (`tests/approval/test_exec_policy.py`):
    - `test_forbidden_prefix_returns_forbidden`: rule `("rm -rf /", FORBIDDEN)` matches `"rm -rf /"` → `FORBIDDEN`.
    - `test_allow_prefix_returns_allow`: rule `("ls", ALLOW)` matches `"ls -la"` → `ALLOW`.
    - `test_first_rule_wins`: rules `[("rm", FORBIDDEN), ("rm", ALLOW)]` → first match `FORBIDDEN`.
    - `test_no_match_calls_heuristics`: no matching rule, heuristics returns `FORBIDDEN` → `FORBIDDEN`.
    - `test_no_match_no_heuristics_returns_prompt`: no rule, no heuristics → `PROMPT`.
    - `test_heuristics_not_called_when_rule_matches`: rule matches → heuristics callable is never invoked.
    - `test_default_rules_exportable`: `DEFAULT_RULES` is a non-empty list of `(str, ExecDecision)` tuples.
    - `test_default_heuristics_returns_prompt`: `default_heuristics("anything")` → `PROMPT`.
    - `test_default_rules_forbid_dangerous_commands`: `classify("rm -rf /", DEFAULT_RULES, default_heuristics)` → `FORBIDDEN`.
    - `test_default_rules_allow_safe_commands`: `classify("ls -la", DEFAULT_RULES, default_heuristics)` → `ALLOW`.
    - `test_classify_is_pure_no_side_effects`: calling `classify` twice with same args returns same result.
  - Verify: `pytest tests/approval/test_exec_policy.py -v`

- [ ] T2: `approval/sandbox.py` — SandboxPolicy + build_sandbox_argv() + platform adapters + SandboxUnavailable
  - Define `SandboxPolicy(StrEnum)` with values `DANGER_FULL_ACCESS = "danger-full-access"`, `READ_ONLY = "read-only"`, `WORKSPACE_WRITE = "workspace-write"`.
  - Define `class SandboxUnavailable(Exception)` — raised when a restrictive policy is active but no native sandbox is found.
  - Implement `build_sandbox_argv(command: str, policy: SandboxPolicy, cwd: Path) -> list[str]`:
    - `DANGER_FULL_ACCESS` → `["bash", "-c", command]` (passthrough, no detection needed).
    - `READ_ONLY` / `WORKSPACE_WRITE` → call `_detect_native_sandbox()`:
      - macOS: if `/usr/bin/sandbox-exec` exists → wrap with a minimal inline seatbelt profile denying writes (`READ_ONLY`) or restricting writes to `cwd` (`WORKSPACE_WRITE`).
      - Linux: if `firejail` on PATH → `["firejail", "--quiet", "--read-only=/", "bash", "-c", command]` (adjusted per policy); else if `bwrap` on PATH → equivalent `bwrap` invocation.
      - If no native sandbox found → raise `SandboxUnavailable(f"No native sandbox available for policy {policy!r}; set --sandbox danger-full-access to proceed without isolation.")`.
  - Tests (`tests/approval/test_sandbox.py`):
    - `test_danger_full_access_returns_bare_argv`: `build_sandbox_argv("ls", DANGER_FULL_ACCESS, tmp_path)` → `["bash", "-c", "ls"]`.
    - `test_sandbox_policy_enum_values`: each enum value matches expected string.
    - `test_sandbox_unavailable_is_exception`: `SandboxUnavailable` is a subclass of `Exception`.
    - `test_restrictive_policy_raises_when_no_sandbox_available` (monkeypatch `_detect_native_sandbox` to return `None`): `build_sandbox_argv("ls", READ_ONLY, tmp_path)` raises `SandboxUnavailable`.
    - `test_restrictive_policy_wraps_when_sandbox_available` (monkeypatch `_detect_native_sandbox` to return `"sandbox-exec"`): result argv is non-empty and does not equal `["bash", "-c", "ls"]`.
  - Platform-specific tests (`tests/approval/test_sandbox_platform.py`, all skip unless native tool present):
    - `test_macos_seatbelt_read_only_blocks_write` (skip if not macOS or no `/usr/bin/sandbox-exec`): run `build_sandbox_argv("touch /tmp/pycodex_test_write", READ_ONLY, tmp_path)` argv as subprocess; assert non-zero exit or file not created.
    - `test_macos_seatbelt_workspace_write_allows_cwd_write` (skip if not macOS or no `/usr/bin/sandbox-exec`): write to `tmp_path/out.txt` succeeds.
    - `test_linux_firejail_blocks_write` (skip if not Linux or no `firejail`): analogous write-blocked assertion.
  - Verify: `pytest tests/approval/test_sandbox.py -v` + `pytest tests/approval/test_sandbox_platform.py -v`

- [ ] T3: `tools/orchestrator.py` — new OrchestratorConfig fields + decision matrix
  - Add to `OrchestratorConfig` (keep `frozen=True`):
    - `exec_policy_fn: Callable[[str], ExecDecision] | None = None`
    - `sandbox_policy: SandboxPolicy | None = None`
  - Add private helper `_canonical_command(tool, args) -> str | None`: calls `getattr(tool, "canonical_command", None)` if set and callable; returns result or `None`. This is the duck-typed entry point for exec policy — tools that don't implement `canonical_command` silently skip exec policy classification.
  - Implement the decision matrix in `execute_with_approval()` after the `is_mutating` check and before the existing session-cache / prompt loop. Exact ordering per the matrix:
    1. If `exec_policy_fn` is set: call `_canonical_command(tool, args)`. If non-None, classify:
       - `FORBIDDEN` → return `ToolError(message="Command blocked by exec policy.", code="forbidden")`.
       - `ALLOW` + sandbox is `None` or `DANGER_FULL_ACCESS` → `await tool.handle(args, cwd)` (bypass prompt and sandbox).
       - `ALLOW` + sandbox is `READ_ONLY` or `WORKSPACE_WRITE` → `await _sandbox_execute(tool, args, cwd, sandbox_policy)` (sandbox runs, prompt bypassed).
    2. If sandbox is `DANGER_FULL_ACCESS` or `None`: fall through to existing approval / prompt logic unchanged (rows 4–5 of matrix).
    3. If sandbox is `READ_ONLY` or `WORKSPACE_WRITE`:
       - `NEVER` → `await _sandbox_execute(tool, args, cwd, sandbox_policy)`; on `SandboxUnavailable` → `ToolError(code="sandbox_unavailable")`; on sandbox denial (non-zero exit or blocked) → `ToolError(code="sandbox_blocked")`.
       - `ON_FAILURE` → attempt sandboxed run; if sandbox denial → call `ask_user_fn` with reason `"retry without sandbox?"`; if approved → `tool.handle(args, cwd)`; else follow existing DENIED/ABORT logic.
       - `ON_REQUEST` / `UNLESS_TRUSTED` → run existing approval loop; on approval execute via `_sandbox_execute`.
  - Add private helper `_sandbox_execute(tool, args, cwd, policy) -> ToolOutcome`: calls `getattr(tool, "sandbox_execute", None)` if available, else falls back to `tool.handle(args, cwd)`. Catches `SandboxUnavailable` and re-raises for the caller to convert to `ToolError`.
  - Preserve all M2 contracts: `ABORT` raises `ToolAborted` (terminal), `DENIED` returns `ToolError(code="denied")` (non-terminal).
  - Tests (`tests/tools/test_orchestrator.py` extensions, all under `pytest -k sandbox or exec_policy`):
    - `test_exec_policy_forbidden_returns_error_immediately`: `exec_policy_fn` returns `FORBIDDEN`; assert `ToolError(code="forbidden")`, tool not called, prompt not called.
    - `test_exec_policy_allow_no_sandbox_skips_prompt_and_runs`: `ALLOW`, no sandbox; assert tool called once, prompt not called.
    - `test_exec_policy_allow_restrictive_sandbox_runs_sandbox_not_prompt`: `ALLOW`, `READ_ONLY`; assert `sandbox_execute` called, prompt not called.
    - `test_exec_policy_skipped_when_canonical_command_absent`: tool without `canonical_command`; exec_policy_fn never invoked.
    - `test_sandbox_never_blocked_returns_error`: `READ_ONLY` + `NEVER`; sandbox denies → `ToolError(code="sandbox_blocked")`; prompt not called.
    - `test_sandbox_on_failure_denied_offers_retry_prompt`: `READ_ONLY` + `ON_FAILURE`; sandbox denies → prompt called once with retry reason; user approves → `tool.handle()` called.
    - `test_sandbox_on_failure_retry_abort_raises_tool_aborted`: same path, user aborts retry → `ToolAborted` raised.
    - `test_sandbox_on_request_approval_runs_sandboxed`: `READ_ONLY` + `ON_REQUEST`; user approves → `sandbox_execute` called.
    - `test_danger_full_access_falls_through_to_existing_approval_loop`: no change to rows 4–5 behavior.
    - `test_existing_on_failure_no_sandbox_unchanged`: `sandbox_policy=None` + `ON_FAILURE` → existing auto-execute behavior; no new prompts.
    - `test_sandbox_unavailable_returns_error`: `_sandbox_execute` raises `SandboxUnavailable` → `ToolError(code="sandbox_unavailable")`.
  - Verify: `pytest tests/tools/test_orchestrator.py -k "sandbox or exec_policy" -v`

- [ ] T4: `tools/shell.py` + `__main__.py` — canonical_command(), sandbox_execute(), --sandbox flag
  - Add `ShellTool.canonical_command(args: dict[str, Any]) -> str | None`:
    - Extracts `args.get("command")`; if missing or invalid returns `None`.
    - Returns `_canonicalize_command_for_approval(command)` — reuses the existing normalization so exec policy and approval key share the same canonical form.
  - Add `ShellTool.sandbox_execute(args: dict[str, Any], cwd: Path, policy: SandboxPolicy) -> ToolOutcome`:
    - Validate `command` and `timeout_ms` exactly as `handle()` does.
    - Call `build_sandbox_argv(command, policy, cwd)` from `approval/sandbox.py` to get the full argv.
    - Spawn subprocess using that argv (replacing the hardcoded `["bash", "-c", command]` in `handle()`).
    - All timeout, output-cap, duration, and error-handling logic is identical to `handle()` — only the argv changes.
    - Propagate `SandboxUnavailable` to caller without catching.
  - Modify `__main__.py` `_build_parser()`:
    - Add `--sandbox` with `choices=[p.value for p in SandboxPolicy]`, `default=SandboxPolicy.DANGER_FULL_ACCESS.value`.
  - Modify `_build_tool_router()` to accept `sandbox_policy: SandboxPolicy` and pass it into `OrchestratorConfig`.
  - Modify `_build_runtime()`, `_run_prompt()`, `_run_prompt_json()`, `_run_tui_mode()` to accept and forward `sandbox_policy`.
  - Tests (`tests/tools/test_shell.py` extensions):
    - `test_canonical_command_returns_normalized_string`: `canonical_command({"command": "/bin/bash -lc 'ls'"})` → normalized string.
    - `test_canonical_command_returns_none_on_missing_command`: `canonical_command({})` → `None`.
    - `test_sandbox_execute_danger_full_access_matches_handle` (mock subprocess): argv passed to subprocess is `["bash", "-c", command]`.
    - `test_sandbox_execute_propagates_sandbox_unavailable` (monkeypatch `build_sandbox_argv` to raise `SandboxUnavailable`): `SandboxUnavailable` propagates out.
  - Tests (`tests/test_main.py` extensions):
    - `test_sandbox_flag_default_is_danger_full_access`: parse `[]` → `args.sandbox == "danger-full-access"`.
    - `test_sandbox_flag_accepted_values`: parse `["--sandbox", "read-only", "x"]` → no error; `args.sandbox == "read-only"`.
    - `test_sandbox_flag_wires_to_orchestrator_config` (monkeypatch `_build_tool_router`): assert called with `sandbox_policy=SandboxPolicy.READ_ONLY` when `--sandbox read-only` passed.
  - Verify: `pytest tests/tools/test_shell.py -k "sandbox or canonical" -v` + `pytest tests/test_main.py -k sandbox -v`

- [ ] T5: Quality gates + milestone verification
  - Run `ruff check . --fix` — must be clean.
  - Run `ruff format .` — must be clean.
  - Run `mypy --strict pycodex/` — must pass on all source files including `approval/exec_policy.py` and `approval/sandbox.py`.
  - Run `pytest tests/ -v` — all tests pass; count vs M4 baseline must increase.
  - Record gate results and new test count in completion checklist below.
  - Verify milestone commands:
    - `python -m pycodex --sandbox read-only --approval on-request "rm -rf /"` → blocked by exec policy, no prompt shown.
    - `python -m pycodex --sandbox danger-full-access --approval never "echo hello"` → runs normally.

## Completion Checklist
- [ ] All T1–T5 done
- [ ] Quality gates all pass (`ruff check`, `ruff format`, `mypy --strict`, `pytest tests/ -v`)
- [ ] Milestone verification commands pass (or blocked by local runtime — document if so)
- [ ] Milestone report includes: files changed, gate results, verification output, risks/assumptions, next milestone recommendation (M6)

## Risks / Assumptions
- `SandboxPolicy` enum values use hyphens (`"danger-full-access"`) matching Codex convention and CLI `--sandbox` choices; Python attribute names use underscores (`DANGER_FULL_ACCESS`).
- `_detect_native_sandbox()` probes at call time (not module load); tests that need a specific platform path monkeypatch it directly.
- Sandbox denial detection (distinguishing a sandbox-blocked exit from a normal command failure) is platform-specific; the initial implementation treats any non-zero exit from the sandboxed run as a candidate for escalation under `ON_FAILURE`, with a note that more precise detection can be added later.
- `canonical_command()` and `sandbox_execute()` are duck-typed optional methods — not added to `ToolHandler` protocol — consistent with `approval_key` precedent. Long-term formalization deferred.
- Exec policy is only applied when `canonical_command()` is present on the tool; file tools (`read_file`, `write_file`, `list_dir`, `grep_files`) do not implement it and are unaffected.
