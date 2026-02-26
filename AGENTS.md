# AGENTS.md

This file defines repo-level behavior for coding work in this project.

## 1. Objectives
- Deliver correct, maintainable changes with minimal complexity.
- Communicate clearly: assumptions, risks, trade-offs, and next steps.
- Prioritize execution over excessive process, while preserving safety.

## 2. Engineering Principles
- **KISS:** Prefer the simplest solution that satisfies requirements.
- **YAGNI:** Do not add speculative features.
- **DRY:** Remove repeated logic when it improves clarity.
- **SOLID:** Apply where it materially improves maintainability.
- **Service Boundaries:** Design around clear module/service boundaries and explicit contracts; extract independent services only when justified.

When proposing non-trivial designs, call out how these principles apply and any intentional trade-offs.

## 3. Architecture Principles
- **API-first:** Define and validate service contracts before implementation details.
- **Separation of concerns:** Keep UX/presentation, domain logic, API surface, and database modeling isolated behind clear interfaces.
- **Independent testability:** Each component must be testable and verifiable in isolation, then in composition.
- **Composable services:** Prefer small, focused components that can be assembled into larger workflows.
- **Experimentation-first:** Favor low-risk experiments/prototypes with explicit validation criteria before broad rollout.

## 4. Standard Workflow
1. **Understand:** Read relevant code, constraints, and current behavior.
2. **Plan:** Define scope, success criteria, and a small implementation path.
3. **Implement:** Make focused changes in logical units.
4. **Verify:** Run quality checks and fix root causes of failures.
5. **Report:** Summarize what changed, why, and any residual risks.

For architectural decisions, provide at least two viable options with a recommendation.
For milestone execution policy and stop/ask boundaries, follow §11 and §12.

## 5. AI-First Operating Model
- **AGENTS is a map, not a dump:** Keep this file short and directive. Put operational detail in:
  - `docs/ai/system-map.md` for architecture map and contracts
  - `docs/ai/harness.md` for evaluation workflows and fixtures
  - `docs/ai/memory.md` for durable decisions and postmortems
- **Repo is the source of truth:** If a decision affects implementation, tests, or operations, record it in-repo in the same change.
- **Non-trivial tasks require explicit acceptance criteria:** Define what "done" means before implementation.
- **Agent changes require harness evidence:** Any change to prompts, tool routing, orchestration, or policy must run the relevant harness tests and report results.
- **Checkpoint before risky branches:** Before broad refactors or policy changes, create a small checkpoint (commit or patch) so work can be resumed safely.
- **Continuous hygiene loop:** At least weekly, review and prune stale instructions, fold recurring issues into docs/tests, and remove redundant guidance.

### Definitions (Trigger Terms)
- **Non-trivial task:** Any change that modifies service/API/event contracts, spans multiple modules, or changes agent behavior (prompts, routing, policy, orchestration).
- **Risky branch:** Any broad refactor or policy change where rollback may be needed (cross-module rewrites, approval/sandbox behavior changes, data/model shape changes).
- **Relevant harness tests:** Targeted `tests/agent_harness/` scenarios that cover the changed behavior surface, plus `tests/agent_harness/test_smoke.py`. If scope is unclear or change is cross-cutting, run the full `tests/agent_harness/` suite.

## 6. Tool and Execution Rules
- Prefer parallel **read-only** operations when independent.
- Run dependent or mutating operations sequentially.
- Use least-privilege queries/commands to reduce noise.
- If a tool fails, capture the failure briefly, retry once if reasonable, then continue with a conservative fallback.

## 7. Safety Rules
- Never run destructive actions (delete/reset/force-push) without explicit user approval.
- Do not revert user changes you did not create.
- If you detect unexpected workspace changes that affect the task, pause and ask how to proceed.
- If requirements are ambiguous, state assumptions and ask only the minimum clarifying questions needed.

`§7` defines hard safety constraints. `§12` defines autonomy defaults.

## 8. Python Standards
- Python 3.11+ with type hints on public APIs.
- Use `pathlib.Path` for path handling.
- Keep imports ordered: stdlib, third-party, local.
- Use async patterns for I/O-heavy paths; avoid blocking calls in async contexts.
- Pydantic v2 conventions:
  - `model_validate()` over `parse_obj()`
  - `model_dump()` over `.dict()`
  - `ConfigDict` over inner `Config`

## 9. Quality Gates
Run the smallest gate set that matches the current scope, then expand only as needed:
- **Bootstrap / initial scaffolding:** `ruff format .`, `ruff check .`
- **Feature work (default):** `ruff check . --fix`, `ruff format .`, targeted `pytest` for touched modules, and `mypy --strict` for touched packages when public type surfaces changed
- **Agent behavior/policy/orchestration changes:** `pytest tests/agent_harness/test_smoke.py -v` plus targeted harness scenarios for the changed behavior (required during feature work)
- **Milestone completion / pre-merge hard gate:** `ruff check . --fix`, `ruff format .`, `mypy --strict pycodex/`, `pytest tests/ -v`, plus `pytest tests/agent_harness/ -v` when relevant
- Add or update component-level tests when introducing new service boundaries or contracts.

### Object-Level Test Rule (Mandatory)
- For every new or modified public contract, behaviorally significant path, or bug-fix path, add or update pytest tests in the same change.
- Private/internal refactors with no behavior or contract change do not require object-by-object test additions; keep or improve existing coverage around touched behavior.
- Tests must be placed under `tests/` mirroring package structure (e.g., `pycodex/core/config.py` -> `tests/core/test_config.py`).
- Iterative exploration is allowed, but required tests must be present before checkpoint/PR/milestone handoff.
- If test execution is blocked by missing tooling, still write the tests and report the blocker explicitly before continuing.

### Risk-Based Test Strategy (Mandatory)
- Optimize for regression detection and fast diagnosis, not coverage percentage targets.
- Prefer fewer high-signal tests over many low-signal tests; avoid adding tests that only mirror implementation details.

#### Unit Tests (Default)
- Unit tests are the default and should cover pure logic, data validation, contract invariants, and error paths.
- Mock only external boundaries (network, filesystem, subprocess, clock); avoid mocking internal domain logic.
- Keep unit tests deterministic and fast enough to run frequently during development.

#### Integration Tests (Boundary-Focused)
- Add integration tests when a change crosses module boundaries (agent loop <-> tools, approval policy <-> store, CLI <-> core wiring).
- Use in-process fakes/test doubles to validate interface contracts and sequencing behavior.
- Assert typed outputs, events, decisions, and side effects; do not assert full free-form model text.

#### End-to-End Tests (Critical Flows Only)
- Maintain a small set of E2E scenarios for critical paths (target: 3-8 core flows).
- E2E tests must cover approval-required actions, tool failure/timeout handling, and at least one multi-step flow.
- Use smoke E2E checks on feature work and full E2E runs at milestone/pre-merge gates when relevant.

#### AI Verifiability Requirements
- Agent-behavior tests must be reproducible: fixed seeds where applicable, controlled time, stable fixture inputs, no live network dependency.
- Prefer model/tool fakes in tests; live-provider calls are optional and must not be the only verification path.
- Validate behavior contracts (tool selected, argument shape, approval path, emitted events, failure handling), not wording style.
- Store scenario fixtures under `tests/agent_harness/fixtures/` with explicit must/must-not expectations.

#### Regression Policy
- Every bug fix must include a regression test that fails before the fix and passes after it when feasible; if not feasible, document why and provide the closest deterministic reproduction/assertion.
- If a test is flaky or low-signal, either fix it immediately or remove/replace it in the same change with rationale in the report.
- Snapshot tests are allowed only for stable, intentional contracts (schemas/events), not for large volatile prose outputs.

If blocked after two attempts on the same failure, report the blocker with diagnosis and options.

## 10. Output Conventions
- Keep responses concise and actionable.
- Use backticks for commands/paths.
- Use fenced code blocks with language tags for multi-line snippets.
- Use UTF-8 (no BOM) for new/modified files.

## 11. Milestone Workflow (When Applicable)
- `engineering-plan.md` is the canonical build roadmap for milestone/build tasks.
- If a task does **not** map to a milestone, follow `§4` and report progress by logical checkpoints.
- For milestone/build tasks, read `engineering-plan.md` first and work **one milestone at a time**.
- A milestone is complete when:
  1. All required quality gates for that milestone/scope pass (§9)
  2. The milestone's verification command from `engineering-plan.md` produces the expected output
- At milestone completion, **stop and report**:
  - Milestone name and files created/modified
  - Quality gate results (pass/fail per gate)
  - Verification command output
  - Proposed next milestone — wait for approval before starting
- If blocked: try one alternative approach, then surface the blocker with diagnosis and options. Max 2 attempts on the same failure.

## 12. Autonomy and Persistence
Proceed without asking for:
- Creating, reading, or modifying files within the project
- Running quality gates (`ruff`, `mypy`, `pytest`)
- Running read-only shell commands (`git status`, `git log`, `ls`, etc.)

Stop and ask before:
- Any destructive operation (delete, reset, force-push) per `§7`
- Starting the next milestone from `engineering-plan.md` when operating under `§11` (always wait for explicit approval after reporting current milestone completion)
- Ambiguous requirements where two interpretations would lead to different architectures

When blocked: follow the max-attempt and reporting rule in §11.

## 13. Living Document Rule
When you discover a pattern that caused repeated errors, confusion, or rework (same issue appears in 2+ tasks or 2+ times within 7 days):
1. Fix the immediate issue
2. At the end of your report, append a **"Proposed AGENTS.md update:"** block with the exact text to add and which file/section it belongs to
3. Do not write the update — wait for user approval

This applies to both this file and any subdirectory `AGENTS.md` files.

## 14. Subdirectory AGENTS.md Files
Each major module has its own `AGENTS.md` with module-specific rules that layer on top of this file. When working in a module, read its `AGENTS.md` first:
- Instruction precedence: system/developer instructions > root `AGENTS.md` > subdirectory `AGENTS.md`.
- Subdirectory rules specialize this file and do not replace it unless explicitly stated.
- `pycodex/core/AGENTS.md` — agent loop, session, model client rules
- `pycodex/tools/AGENTS.md` — tool protocol, error format, mutating semantics
- `pycodex/approval/AGENTS.md` — approval store, stateless policy rules
- `pycodex/cli/AGENTS.md` — rendering separation, no business logic in CLI
