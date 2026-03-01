# M5 Code & Architecture Review

_Reviewed: 2026-02-28_

## Summary

M5 is largely well-executed — the three-layer design (exec policy → sandbox isolation → approval), Protocol-based duck typing, and decision matrix wiring are all sound. No critical bugs. There are **two major correctness issues** and several minor gaps to address before M6.

---

## Architecture Findings

### Major

**[M-1] `_is_sandbox_denial` false positives** — `pycodex/tools/orchestrator.py:295–305`

Any `ToolResult` with a non-zero exit code is classified as a sandbox denial. A legitimate `ls /nonexistent` (exit 2) triggers the "retry without sandbox?" prompt under `ON_FAILURE`. The function name promises sandbox-denial detection but actually detects any non-zero exit. `todo-m5.md` notes this as a known risk but the false-positive scope is larger than acknowledged.

**[M-2] Exec policy whitespace evasion vectors** — `pycodex/approval/exec_policy.py:52–57`

Two prefix-matching bypasses exist:
- `rm -rf/` (no space before path) → `PROMPT`, not `FORBIDDEN`
- `rm  -rf /` (double internal space) → `PROMPT`, not `FORBIDDEN`

Neither `canonical_command()` nor `classify()` normalizes internal whitespace. The security property "closes the most common evasion vectors" is incomplete.

### Minor

**[m-1]** `SandboxUnavailable` under `ON_FAILURE` returns a hard error without offering the retry prompt — undocumented, untested (`pycodex/tools/orchestrator.py:124–141`)

**[m-2]** `assert bridge is not None` in `pycodex/__main__.py:218` — assertions are elided under `python -O`; should be `if bridge is None: raise RuntimeError(...)`

**[m-3]** `store.put(key, retry_decision)` in the `ON_FAILURE` retry path is a silent no-op for `APPROVED` (single-use) — misleading to readers without a comment (`pycodex/tools/orchestrator.py:140`)

**[m-4]** `_seatbelt_escape` doesn't escape `(` `)` — a crafted `cwd` could inject seatbelt rules (`pycodex/approval/sandbox.py:102–103`); low practical risk since `cwd` is user-controlled, but worth documenting

**[m-5]** `sandbox_policy is None or sandbox_policy == SandboxPolicy.DANGER_FULL_ACCESS` repeated 6× in `orchestrator.py` — extract to `_is_unsandboxed(policy)` helper

**[m-6]** `UNLESS_TRUSTED` is silently identical to `ON_REQUEST` with no comment or TODO explaining the deferral (`pycodex/tools/orchestrator.py:143–152`)

---

## Code Quality Findings

### Major

**[Q-1]** Same root as M-1: `_is_sandbox_denial` violates its own contract — the docstring/name imply sandbox-specific detection but the implementation is a general non-zero exit check.

### Minor

**[q-1]** `default_heuristics` uses `_ = command` to suppress unused-arg lint — should be `_command: str` in the signature (`pycodex/approval/exec_policy.py:31`)

**[q-2]** Firejail `--read-only=/ --read-write=<cwd>` override may not work on older firejail versions; `WORKSPACE_WRITE` on Linux untested (`pycodex/approval/sandbox.py:76–80`)

**[q-3]** bwrap `--unshare-all` silently severs the network namespace — commands like `curl`/`git clone` fail inside the sandbox; not documented, M6 network rules will need to revisit (`pycodex/approval/sandbox.py:83–99`)

**[q-4]** `classify()` docstring doesn't mention that internal multi-space is NOT normalized — relevant for security-sensitive callers

**[q-5]** `_is_sandbox_denial` silently assumes `ToolResult.body` has the shape `{"metadata": {"exit_code": int}}` with no comment documenting this dependency on `ShellTool`'s output format

---

## Test Coverage Gaps

| Gap | Location |
|-----|----------|
| `SandboxUnavailable` + `ON_FAILURE` not tested | `tests/tools/test_orchestrator.py` |
| `WORKSPACE_WRITE` policy never tested in orchestrator | `tests/tools/test_orchestrator.py` |
| `UNLESS_TRUSTED` has zero test coverage anywhere | — |
| `rm -rf/` and `rm  -rf /` evasion cases not tested | `tests/approval/test_exec_policy.py` |
| `_is_sandbox_denial` false positive (legitimate failure) not tested | `tests/tools/test_orchestrator.py` |
| `sandbox_execute` with `WORKSPACE_WRITE` not tested | `tests/tools/test_shell.py` |
| Firejail `WORKSPACE_WRITE` not covered in platform tests | `tests/approval/test_sandbox_platform.py` |

---

## Prioritized Recommendations

| Priority | Finding | Fix |
|----------|---------|-----|
| **P1** | M-1 / Q-1 | Document `_is_sandbox_denial` false-positive scope with a comment + test locking in current behavior; long-term: have `sandbox_execute` return `ToolError(code="sandbox_blocked")` only on actual OS-level blocks |
| **P2** | M-2 | Add regression tests for `rm -rf/` and `rm  -rf /` evasion; document internal-whitespace non-normalization in `classify()` docstring |
| **P3** | m-2 | Replace `assert bridge is not None` with `if bridge is None: raise RuntimeError(...)` |
| **P4** | m-3 | Add comment to `store.put(key, retry_decision)` clarifying the no-op behavior for `APPROVED` |
| **P5** | m-1 | Add `test_sandbox_unavailable_on_failure_returns_error_without_retry_prompt` — document whether no-prompt behavior is intentional |
| **P6** | gaps | Add `WORKSPACE_WRITE` and `UNLESS_TRUSTED` orchestrator tests |
| **P7** | q-3 | Add comment to bwrap `--unshare-all` noting the network-namespace side effect |
| **P8** | m-5 | Extract `_is_unsandboxed(policy)` helper to eliminate 6× repeated condition |
