Implement the next incomplete milestone from engineering-plan.md.

---

## Step 1 — Identify current state
- Read `engineering-plan.md` in full
- List all files required for each milestone
- Check which of those files already exist on disk
- Determine the next incomplete milestone (first one with any missing files)
- Output: "Next milestone: M? — [name]. Missing files: [list]"

## Step 2 — Load context
- Read root `AGENTS.md`
- Read each subdirectory `AGENTS.md` for every module this milestone touches
- Note any rules that constrain implementation choices (e.g., async-only, protocol exactness)

## Step 2.5 — Plan (present before implementing)

Break the milestone into independent, verifiable subtasks. For each subtask:
- **ID**: T1, T2, T3, … (in implementation order)
- **File**: the exact file path to create or modify
- **What it does**: one sentence describing its responsibility
- **Inputs**: what it depends on (other files, env vars, external APIs)
- **Outputs / contract**: what it exposes (classes, functions, types) that other subtasks consume
- **Verification**: a specific, runnable check that confirms this subtask is correct in isolation (e.g., `python -c "from pycodex.core.config import Config; c = Config(); print(c.model)"`)
- **Depends on**: IDs of subtasks that must complete before this one starts

Present the full subtask table, then **stop and wait for approval** before writing any code.

Example subtask table format:
```
T1 | pycodex/core/config.py     | Pydantic Config model       | OPENAI_API_KEY env var        | Config class with .model, .api_key, .cwd | python -c "from pycodex.core.config import Config; print(Config())" | —
T2 | pycodex/core/session.py    | Message history container   | T1 (Config)                   | Session class, append_*/to_prompt()       | python -c "from pycodex.core.session import Session" | T1
...
```

## Step 3 — Implement subtasks
- Execute subtasks in dependency order (subtasks with no dependencies first, then unblock dependents)
- Independent subtasks (no shared deps) may be implemented in parallel
- After writing each file, run its individual verification check from Step 2.5
- If a subtask's verification fails: fix it before moving to any subtask that depends on it
- Do not skip verifications — a subtask is not done until its check passes

## Step 4 — Run quality gates (all files)
Run in order after all subtasks are complete:
- `ruff check . --fix`
- `ruff format .`
- `mypy --strict pycodex/`
- `pytest tests/ -v`

Fix any failures before proceeding. Max 2 attempts per failure before reporting as a blocker.

## Step 5 — Run milestone verification
- Run the exact verification command from `engineering-plan.md` for this milestone
- Capture the full output

## Step 6 — Stop and report
```
**Milestone**: M? — [name]
**Subtasks completed**: T1, T2, T3, … (all N)

**Files created/modified**:
- path/to/file.py — one-line description

**Quality gates**:
- ruff check: PASS / FAIL
- ruff format: PASS / FAIL
- mypy: PASS / FAIL
- pytest: PASS / FAIL (N passed, N failed)

**Verification**:
Command: `<command>`
Output:
<actual output>

**Status**: COMPLETE / BLOCKED
**Next milestone**: M? — [name] — waiting for your approval before starting
```

Do not start the next milestone. Wait for explicit user approval.
