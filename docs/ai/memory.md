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
