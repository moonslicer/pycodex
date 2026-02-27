# pycodex/cli — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## Current State
- There is no production `pycodex/cli/*.py` implementation yet (Milestone 4 scope).
- The current CLI entrypoint and wiring live in `pycodex/__main__.py`.

## Responsibilities (Current)
- Argument parsing, logging setup, and top-level error display live in `__main__.py`.
- Runtime tool registration for default CLI behavior also lives in `__main__.py`.
- Core business logic stays in `pycodex/core`, `pycodex/tools`, and `pycodex/approval`.

## If/When `pycodex/cli` Is Added
- Keep CLI modules as presentation/input orchestration only; do not move agent/tool business rules into UI modules.
- Keep mode selection centralized in one entrypoint module.
- Interactive approval UX must use injected callbacks (`ask_user_fn`) rather than hardcoded calls in policy/orchestrator modules.

## Error Display
- Top-level CLI exception handling may render to stderr in the entrypoint.
- Library modules (`core`, `tools`, `approval`) must not print directly.
