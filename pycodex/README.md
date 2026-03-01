# pycodex Package Guide

This package contains the Python runtime for the agent, tool system, approval flow, and protocol contracts.

## Module Map

- `pycodex/__main__.py`: CLI entrypoint, runtime wiring, top-level error handling.
- `pycodex/core/`: agent loop, model client integration, session state, event adapters, TUI bridge.
- `pycodex/tools/`: tool protocol/registry and concrete tool handlers.
- `pycodex/approval/`: approval policy types and approval decision cache behavior.
- `pycodex/protocol/`: typed protocol event schemas used by JSON and TUI modes.

## Common Change Paths

Add a new tool:
1. Create a new module under `pycodex/tools/`.
2. Implement `ToolHandler` contract in `pycodex/tools/base.py`.
3. Register it in `pycodex/__main__.py` runtime tool wiring.
4. Add tests under `tests/tools/`.

Change approval behavior:
1. Update `pycodex/approval/policy.py` and/or `pycodex/tools/orchestrator.py`.
2. Add/adjust tests in `tests/approval/`, `tests/tools/test_orchestrator.py`, and `tests/agent_harness/` as needed.

Change event/protocol shape:
1. Update `pycodex/protocol/events.py`.
2. Update emitters/adapters in `pycodex/core/`.
3. Update TUI protocol types in `tui/src/protocol/types.ts` in the same change.
4. Add/update Python and TUI tests for the changed contract.

## Local Validation

- `ruff check . --fix`
- `ruff format . --check`
- `mypy --strict pycodex/`
- targeted `pytest` for touched modules (and harness tests for behavior changes)
