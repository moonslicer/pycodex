# pycodex

Agentic Python runtime plus terminal UI, built around explicit contracts and verifiable behavior.

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

## Development Checks

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
- `todo-m5.md`: current active milestone tracker.

## Documentation Index

See [`docs/README.md`](docs/README.md) for where each documentation file lives and when to update it.

## CI

CI is defined in `.github/workflows/ci.yml`. It runs lint/type/test/security checks for Python and TUI, plus optional E2E on pull requests to `main`.
