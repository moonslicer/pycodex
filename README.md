# pycodex

`pycodex` is an AI agent runtime for the terminal that focuses on one thing: reliable orchestration.
It combines tool use, approval policy, typed events, and reproducible tests so agent behavior is inspectable and maintainable.
It is inspired by Codex and rewritten in Python as a simplified agent runtime that preserves the core features.

## Why This Project Is Different

Most agent demos optimize for a flashy output. `pycodex` optimizes for production engineering concerns:

- Explicit tool contracts and deterministic execution paths.
- Approval and sandbox controls for mutating actions.
- Typed protocol events for machine-readable observability.
- Replayable scenarios and harness tests for behavior regressions.

If you want to study how modern agent systems are actually wired end-to-end, this repo is designed to make that visible.

## Capability Snapshot

- Agent execution loop with structured tool calling (`shell`, `read_file`, `write_file`, `list_dir`, `grep_files`).
- Approval-aware orchestration with session-scoped decision caching.
- Multi-surface operation: CLI, JSON event stream, and interactive TUI.
- Skill discovery/injection with deterministic precedence and replay-safe behavior.
- Offline fake-model mode for deterministic local development.
- Session rollout recording/replay and compaction support.

## Quickstart

Requirements:
- Python 3.11+
- Node.js (for `tui/`)

Setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
npm --prefix tui install
```

## Run

Single prompt:

```bash
python -m pycodex "List Python files in this repo."
```

Prompt with approval gating:

```bash
python -m pycodex --approval on-request "Create a file named notes.txt with hello."
```

JSON event mode:

```bash
python -m pycodex --json "Summarize this repository."
```

TUI mode:

```bash
python -m pycodex --tui-mode
```

Local fake model (no network call):

```bash
PYCODEX_FAKE_MODEL=1 python -m pycodex "dry-run prompt"
```

Inspect exact LLM request payload (debug to stderr):

```bash
python -m pycodex --dump-llm-request "Summarize this repository." 2>/tmp/pycodex-llm.log
tail -f /tmp/pycodex-llm.log
```

TUI + payload dump:

```bash
PYCODEX_TUI_DUMP_LLM_REQUEST=1 node tui/dist/src/index.js \
  2> >(tee -a /tmp/pycodex-tui-llm.log >&2)
```

Note: dumps are emitted only for real model calls. If `PYCODEX_FAKE_MODEL=1` is set,
no OpenAI request is made, so there is nothing to dump.

## Engineering Quality Gates

Standard local review:

```bash
make review
```

Full review plus hygiene checks:

```bash
make review-hygiene
```

Core Python gate:

```bash
ruff check . --fix
ruff format . --check
mypy --strict pycodex/
pytest tests/ --ignore=tests/agent_harness -m "not e2e" -v
pytest tests/agent_harness/ -v
```

Optional live E2E:

```bash
pytest tests/ -m e2e -v
```

## Repository Map

- `pycodex/`: Python runtime, tools, approval policy, protocol models.
- `tests/`: unit/integration/e2e/harness tests.
- `tui/`: React + Ink terminal UI.
- `docs/`: architecture, harness workflow, memory log, milestone trackers.
- `engineering-plan.md`: milestone roadmap and architecture details.
- `todo.md`: active milestone tracker and decomposition.

## Documentation Index

See [`docs/README.md`](docs/README.md) for where each documentation file lives and when to update it.

## CI

CI is defined in `.github/workflows/ci.yml`. It runs lint/type/test/security checks for Python and TUI, plus optional E2E on pull requests to `main`.

## License

Licensed under Apache License 2.0. See `LICENSE`.
