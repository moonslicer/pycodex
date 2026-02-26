Implement a single TODO task from `todo.md` with explicit plan approval before coding.

Use `$ARGUMENTS` as the requested task ID (example: `T2`). If no task ID is provided, select the first unchecked task.

---

## Step 1 — Identify the target task
- Read `todo.md`
- Parse all task IDs (`T1`, `T2`, ...)
- Resolve target task:
  - If `$ARGUMENTS` contains a valid ID, use it
  - Else use the first unchecked task (`- [ ]`)
- Output:
  - `Target task: T?`
  - Task summary (file, description, dependencies, verify command)
  - If task is already checked, stop and report `ALREADY COMPLETE`

## Step 2 — Load constraints and context
- Read root `AGENTS.md`
- Read subdirectory `AGENTS.md` for modules touched by the target task
- Read currently relevant files for the task and existing tests under `tests/`
- Identify explicit constraints that affect implementation choices

## Step 2.5 — Plan + metrics (required before implementation)
Provide these sections and then **stop for user approval**:

1. **Scope I’ll build**
   - Exactly what this task includes and excludes

2. **Implementation plan**
   - Numbered steps with concrete file-level changes
   - Note dependencies and ordering

3. **Success metrics (approval criteria)**
   - Functional checks
   - Contract/architecture checks
   - Verification commands (task-level and test-level)
   - Scope-appropriate quality gates

4. **Assumptions**
   - Minimal assumptions; call out anything that could change architecture

Do not write code before approval.

## Step 3 — Implement task only
- Edit only files required for this target task
- Add/update tests for any public contract or behavior change in this task
- Keep changes minimal (KISS/YAGNI/DRY)
- Do not start the next task

## Step 4 — Verify task
Run:
1. The task verify command from `todo.md`
2. `ruff check . --fix`
3. `ruff format .`
4. Targeted `pytest` for touched modules
5. `mypy --strict` for touched package(s) if public type surfaces changed

If a check fails, fix and rerun. Max 2 attempts per same failure before reporting a blocker.

## Step 5 — Update TODO + report
- Mark the target task as complete in `todo.md` only after all checks pass
- Report:

```
**Task**: T? — [name]
**Status**: COMPLETE / BLOCKED / ALREADY COMPLETE

**Files created/modified**:
- path — one-line purpose

**Verification**:
- Task verify command: PASS / FAIL
- ruff check: PASS / FAIL
- ruff format: PASS / FAIL
- pytest (targeted): PASS / FAIL
- mypy (if run): PASS / FAIL

**Notes**:
- Risks or follow-ups (if any)
- Next recommended task: T?

**Recurring patterns found** (§13 check):
- [Issue] — [appeared in: T?, T?] — [proposed AGENTS.md update]
- None found
```
