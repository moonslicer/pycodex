# Test Guide

This directory contains deterministic coverage for Python runtime behavior and contract-level agent checks.

## Suite Layout

- `tests/core/`: agent loop, model client mapping, session, event adapter, TUI bridge behavior.
- `tests/tools/`: tool implementations, router/registry, orchestrator approval flow.
- `tests/approval/`: approval store and policy-specific rules.
- `tests/protocol/`: protocol schema validation and JSON round-trip coverage.
- `tests/agent_harness/`: scenario-based behavior contract tests.
- `tests/e2e/`: critical flow end-to-end tests (mostly local/fake, plus opt-in live checks).
- `tests/test_main.py`: CLI wiring and mode behavior for `python -m pycodex`.

## Useful Commands

Fast local checks (no harness/e2e):

```bash
pytest tests/ --ignore=tests/agent_harness -m "not e2e" -v
```

Harness only:

```bash
pytest tests/agent_harness/ -v
```

E2E only:

```bash
pytest tests/ -m "e2e" -v
```

Single file:

```bash
pytest tests/tools/test_orchestrator.py -v
```

## Markers

- `unit`: fast isolated tests.
- `integration`: module-boundary tests with in-process fakes.
- `e2e`: critical full-flow tests (opt-in, environment-dependent).
- `agent_harness`: scenario-based agent behavior contract tests.

## Test Expectations

- Prefer deterministic assertions over output-style assertions.
- Validate contract shape and behavior (events, tool calls, args, statuses).
- For bug fixes, add a regression test when deterministic reproduction is feasible.
