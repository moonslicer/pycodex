# AI Memory Log

Use this file for durable decisions that should not remain only in chat history.

## Entry Template
```
## YYYY-MM-DD - Short title
Context:
- What changed and why now.

Decision:
- Concrete decision and scope.

Impact:
- Affected files/modules/contracts.

Verification:
- Commands run and key outcomes.

Follow-ups:
- Any deferred work, owner, and trigger for revisit.
```

## Principles
- Record decisions that affect behavior, architecture, or policy.
- Keep entries concise and factual.
- Link to PRs/issues/commits when available.

## 2026-02-27 - Milestone 2 approval contracts stabilized
Context:
- Milestone 2 introduced approval gating, session-scoped approval caching, and mutating/read-only tool separation.
- Follow-up hardening was needed to resolve ambiguity in abort behavior and shell approval-key stability.

Decision:
- `ABORT` is terminal control flow for the active turn.
- `ToolAborted` is raised in `tools/orchestrator.py`, propagated by `tools/base.py`, and handled in `core/agent.py` as immediate turn termination.
- `shell` approval keys use conservative canonicalization:
  - normalize wrapper-equivalent `bash -lc` forms
  - normalize whitespace only for safe token-only inline commands
  - keep semantically sensitive inline shell forms distinct
- `write_file` approval key remains the resolved absolute file path.

Impact:
- `pycodex/tools/orchestrator.py`
- `pycodex/tools/base.py`
- `pycodex/core/agent.py`
- `pycodex/tools/shell.py`
- `tests/tools/test_orchestrator.py`
- `tests/tools/test_shell.py`
- `tests/core/test_agent.py`
- `tests/agent_harness/test_approval_policy_scenarios.py`

Verification:
- `ruff check . --fix` passed.
- `ruff format .` passed.
- `mypy --strict pycodex/` passed.
- `pytest tests/ -v` passed (`141 passed, 1 skipped` in local run; skip is the live OpenAI e2e when endpoint is unreachable).

Follow-ups:
- Milestone 2 manual verification command (`python3 -m pycodex --approval on-request ...`) depends on local runtime OpenAI client setup and reachable endpoint; keep the completion checklist item blocked until that environment check is satisfied.

## 2026-03-07 - Architecture docs converted to current-state references
Context:
- `engineering-plan.md` and `summary-plan.md` still described already-shipped compaction and replay work as pending tasks.
- `docs/ai/system-map.md` and `docs/README.md` still referenced a non-existent active `todo-m5.md` tracker.

Decision:
- Rewrote `engineering-plan.md` as a current-state architecture document with locked contracts, implementation scope, and near-term priorities.
- Rewrote `summary-plan.md` as a concise status/contract snapshot aligned to the implemented runtime.
- Updated `docs/ai/system-map.md` and `docs/README.md` to reference current sources of truth and archived milestone artifacts under `docs/archive/`.

Impact:
- `engineering-plan.md`
- `summary-plan.md`
- `docs/ai/system-map.md`
- `docs/README.md`
- `docs/ai/memory.md`

Verification:
- Manual source review against current runtime modules in `pycodex/core/`, `pycodex/tools/`, `pycodex/approval/`, and `pycodex/protocol/`.
- Consistency check for stale `todo-m5.md` references in updated docs.

Follow-ups:
- Keep architecture docs synchronized whenever protocol events, compaction contracts, or session/rollout semantics change.
