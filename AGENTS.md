# AGENTS.md

This file defines repo-level operating rules for coding agents.

## 1) Rule Priority
- Precedence: system/developer instructions > root `AGENTS.md` > subdirectory `AGENTS.md`.
- If a module has its own `AGENTS.md`, read it before editing that module.
- Known module-level files:
  - `pycodex/core/AGENTS.md` — agent loop, session, model client rules
  - `pycodex/tools/AGENTS.md` — tool protocol, error format, mutating semantics
  - `pycodex/approval/AGENTS.md` — approval store, stateless policy rules
  - `pycodex/cli/AGENTS.md` — rendering separation, no business logic in CLI
  - `tui/AGENTS.md` — TypeScript/React/Ink architecture and frontend quality rules

## 2) Core Outcome
- Deliver correct, maintainable changes with minimal complexity.
- Prefer execution over process unless safety or quality would be reduced.
- Design around clear module boundaries, explicit contracts, and separation of concerns.
- Define and validate service contracts (API-first) before implementation details.
- Favor small experiments with explicit validation criteria before broad implementation.

## 3) Definitions
- **Non-trivial task:** changes service/API/event contracts, spans modules, or changes agent behavior (prompt, routing, policy, orchestration).
- **Behavior/contract change:** any user-visible behavior, public API, schema, event shape, decision policy, or persisted data shape change.
- **Mechanical change:** formatting, rename/move, comment/docs-only, dependency bump without behavior change.
- **Risky branch:** any broad refactor or policy change where rollback may be needed (cross-module rewrites, approval/sandbox behavior changes, data/model shape changes).
- **Oversize task:** estimated >600 changed lines (additions + deletions) for behavior/contract work.
- **Relevant harness tests:** targeted `tests/agent_harness/` scenarios for the changed behavior surface, plus `test_smoke.py`. If scope is unclear or change is cross-cutting, run the full `tests/agent_harness/` suite.

## 4) Standard Workflow
1. Understand current behavior and constraints.
2. Plan smallest safe change with acceptance criteria.
3. Implement in focused units.
4. Verify with matching quality gates.
5. Report what changed, evidence, and residual risks.
- If blocked, try one alternative, then report blocker with options.
- Max two attempts on the same failure.

## 5) Safety and Autonomy
- Never run destructive actions (delete/reset/force-push) without explicit approval.
- Do not revert user changes you did not create.
- If unexpected workspace changes affect the task, pause and ask.
- Proceed without asking for normal file edits and standard quality commands.
- Ask only when requirements are ambiguous enough to change architecture.

## 6) Quality Gates
Run the smallest gate set that matches scope:
- **Feature work (default):** `ruff check . --fix`, `ruff format .`, targeted `pytest`, and `mypy --strict` for touched public type surfaces.
- **Agent behavior/policy/orchestration changes:** `pytest tests/agent_harness/test_smoke.py -v` plus targeted harness scenarios.
- **Pre-merge hard gate:** `ruff check . --fix`, `ruff format .`, `mypy --strict pycodex/`, `pytest tests/ -v`, and `pytest tests/agent_harness/ -v` when relevant.
- **Full repo review request** (when user asks to "run all tests", "run all tests and reviews", or equivalent): run both Python and TUI gates:
  - `.venv/bin/ruff check .`
  - `.venv/bin/ruff format --check .`
  - `.venv/bin/mypy --strict pycodex/`
  - `.venv/bin/pytest tests -v`
  - `cd tui && npm run typecheck`
  - `cd tui && npm run lint`
  - `cd tui && npm test`

### Test Requirements
- For each new/modified public contract, behavior-significant path, or bug fix, add/update tests in the same change.
- Place tests under `tests/` mirroring package structure (e.g., `pycodex/core/config.py` → `tests/core/test_config.py`).
- Bug fixes require a regression test when deterministic reproduction is feasible; otherwise document why and add closest deterministic assertion.
- Prefer high-signal deterministic tests; remove or replace flaky/low-signal tests in the same change.

### Test Strategy
- **Unit (default):** Cover pure logic, data validation, contract invariants, error paths. Mock only external boundaries (network, filesystem, subprocess, clock) — never mock internal domain logic.
- **Integration (boundary-focused):** Add when a change crosses module boundaries. Use in-process fakes/test doubles. Assert typed outputs, events, and side effects — not free-form model text.
- **E2E (critical flows only):** Maintain a small set (3-8) for critical paths covering approval-required actions, tool failure/timeout handling, and at least one multi-step flow.
- **AI verifiability:** Agent-behavior tests must be reproducible — fixed seeds, controlled time, stable fixture inputs, no live network dependency. Validate behavior contracts (tool selected, argument shape, approval path, emitted events), not wording style. Store scenario fixtures under `tests/agent_harness/fixtures/`.

## 7) Anti-Slop Guardrails
- Default target for behavior/contract work: <=600 changed lines.
- If estimated >600 lines, split into independently verifiable tasks before coding when practical.
- Oversize exceptions allowed only with written rationale:
  - Why splitting is unsafe or impractical.
  - Why change is mechanical/low-risk or must remain atomic.
  - Rollback plan.
- For non-trivial milestone work, track decomposition in `todo.md` with one behavior/contract change per task and explicit acceptance criteria.
- Milestone-specific trackers are valid when present (for example `todo-m2.md`); treat the active milestone tracker as canonical for that milestone.
- Do not mark task/milestone complete if acceptance criteria or required tests are missing.

## 8) Milestones (When Applicable)
- `engineering-plan.md` is canonical for milestone/build tasks.
- Work one milestone at a time.
- Milestone completion requires:
  1. Required quality gates pass.
  2. Milestone verification command produces expected output.
- At completion, stop and report:
  1. Milestone name and files changed.
  2. Gate results (pass/fail).
  3. Verification command output.
  4. Proposed next milestone.
- Wait for explicit approval before starting the next milestone.

### Build Command Gate (Required)
- Applies to command-style build requests (for example: `build-task`, `build-tasks`, `build-milestone`).
- Before doing implementation work, load and follow the matching command spec in `.claude/commands/` (for example `.claude/commands/build-task.md`).
- Plan-first is mandatory for all build commands (not only parallel work): present scope, file-level plan, success metrics/verification commands, and assumptions, then stop for explicit user approval.
- Do not create or edit implementation files before approval. If no matching command spec exists, fall back to the same plan-first approval gate.

## 9) Coding Defaults (Python)
- Python 3.11+.
- Type hints on public APIs.
- `pathlib.Path` for path handling.
- Import order: stdlib, third-party, local.
- Avoid blocking calls in async contexts.
- Pydantic v2: `model_validate()`, `model_dump()`, `ConfigDict`.
- Logging: module loggers via `getLogger(__name__)` only; configure only at the entry point (`__main__.py`).

## 10) Documentation Placement
- Keep this file short and directive.
- Put architecture/contracts in `docs/ai/system-map.md`.
- Put harness workflows in `docs/ai/harness.md`.
- Put durable decisions/postmortems in `docs/ai/memory.md`.

## 11) Parallel Task Isolation (Required)
Applies when user requests parallelized work (for example: "start subagents", "build-tasks T4/T5").

- Plan-first gate: provide a per-task plan and wait for explicit user approval before making edits.
- One task, one branch, one worktree:
  - Branch name format: `codex/<task-id>` (example: `codex/t4`).
  - Create a dedicated worktree per parallel task.
  - Never run two parallel tasks in the same worktree.
- Change isolation:
  - A subagent may edit only files needed for its assigned task.
  - If overlap with another active task is required, stop and ask for sequencing.
- Commit isolation:
  - Do not mix multiple tasks in one commit.
  - Use conventional commit subjects with scope (examples: `feat(tools): implement shell tool`, `fix(core): handle offset bounds`).
  - Do not include transient task IDs (for example `T4`, `T5`) in commit titles; if needed, place them in the commit body or PR description.
- Integration:
  - Integrate task branches individually (merge/cherry-pick per task).
  - Report per task: branch, commit SHA, files changed, tests run.
- If pre-existing mixed changes are detected, pause and ask whether to split or stash before continuing.

## 12) Living Document Rule
When you discover a pattern that caused repeated errors, confusion, or rework (same issue appears in 2+ tasks or 2+ times within 7 days):
1. Fix the immediate issue.
2. At the end of your report, append a **"Proposed AGENTS.md update:"** block with the exact text to add and which file/section it belongs to.
3. Do not write the update — wait for user approval.

This applies to both this file and any subdirectory `AGENTS.md` files.
