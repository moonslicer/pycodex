Review code changes for AGENTS.md compliance, design quality, and anti-patterns before committing.

Use `$ARGUMENTS` to specify scope: blank = working tree diff, branch name = diff vs main, `PR#NNN` = PR diff.

---

## Step 1 — Get the diff

- If no arguments: `git diff HEAD` (staged + unstaged)
- If argument is a branch name: `git diff main...$ARGUMENTS`
- If argument matches `PR#NNN`: `gh pr diff NNN`
- List all changed `.py` files with their change type (added/modified/deleted)
- If no Python files changed: report `SKIP — no Python changes` and stop

## Step 2 — Load review context

- Read root `AGENTS.md` (focus on §2, §5, §8, §9)
- Read subdirectory `AGENTS.md` files for any modules touched by the diff
- Read `docs/ai/memory.md` for known recurring patterns to check against
- Read `todo.md` to understand current task context

## Step 3 — AGENTS.md compliance scan (FAIL = blocks commit)

For each changed file, check:

1. **Type hints**: Every new/modified public function/method has type annotations
2. **Test coverage**: Every new public contract has a corresponding test added in the same diff
3. **Async safety**: No blocking calls (`time.sleep`, synchronous `open()`, `requests.get`) in async functions
4. **Tool isolation**: No tool code added to an existing tool file (each tool must be its own file per `tools/AGENTS.md`)
5. **CLI purity**: No business logic in files under `pycodex/cli/` (per `cli/AGENTS.md`)
6. **Pydantic v2**: Uses `model_validate()`, `model_dump()`, `ConfigDict` — not `parse_obj()`, `.dict()`, inner `Config`
7. **Session integrity**: No direct mutation of `Session._history` outside `Session` methods
8. **Model client contract**: No raw dicts returned from `model_client` — must use typed dataclasses
9. **No print()**: No `print()` calls in non-CLI files
10. **Anti-slop**: Estimated diff size <=600 changed lines; if larger, flag for split rationale

Each violation: report `FAIL — file:line — description — suggested fix`

## Step 4 — Design quality review (CONCERN = advisory, does not block)

For each new class or function:

1. **Function length**: Functions >40 lines → CONCERN
2. **YAGNI**: Parameters or config options with no current callers → CONCERN
3. **TODO tracking**: Any `TODO`/`FIXME` comments not tracked in `todo.md` → CONCERN
4. **Naming clarity**: Public names that are ambiguous or inconsistent with existing conventions → CONCERN
5. **Error handling**: Overly broad `except Exception` or silent `except: pass` → CONCERN
6. **Unnecessary type coercion**: e.g. `str(path)` where `Path` is accepted natively → CONCERN
7. **Module-level concurrency primitives**: `asyncio.Semaphore()`, `threading.Lock()` etc. created at import time — prefer lazy init inside a function → CONCERN
8. **Unused sentinel variables**: `_ = arg` to silence linters instead of redesigning the interface → CONCERN
9. **String-based dispatch on typed unions**: `getattr(obj, "type") == "foo"` when `isinstance(obj, FooClass)` is available → CONCERN
10. **Multi-accumulator precedence logic**: two parallel lists with `if list_a: return list_a else: return list_b` — consolidate into one → CONCERN
11. **Missing module docstrings**: any `.py` file without a top-level docstring → CONCERN

Each finding: report `CONCERN — file:line — description`

## Step 5 — Report

```
**Review scope**: [working tree / branch / PR#NNN]
**Files reviewed**: N files changed (A added, M modified, D deleted)

**Status**: PASS / FAIL

**FAIL items** (must fix before commit):
- file:line — [check name] — description — fix: [suggestion]

**CONCERN items** (advisory):
- file:line — description

**Next recommended action**: /commit | fix [file:line] | split into smaller changes

**Recurring patterns found** (§13 check):
- [Issue] — [appeared in: T?, T?] — [proposed AGENTS.md update]
- None found

**Proposed AGENTS.md update**: [exact text to add and target section] | None
```

## Step 6 — Fix and re-review (if FAIL items exist)

- For each FAIL item: propose a specific fix
- Ask user: "Should I apply these fixes?"
- If approved: implement fixes, then re-run Steps 3-5 on the updated diff
- Report delta: "N issues resolved, M remaining"
- Repeat until PASS or user decides to proceed anyway
