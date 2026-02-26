# pycodex

Agentic Python project scaffold focused on explicit contracts, composable modules, and verifiable behavior.

## Requirements

- Python 3.11+
- `git` (required for pre-commit hook execution)

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install ruff mypy pytest pytest-asyncio pydantic pre-commit
```

## Build / Install

This repository currently uses source-layout execution (tests import from the repo root) and does not require packaging to run checks.

Optional editable install (if you want package-style imports from anywhere):

```bash
pip install -e .
```

## Run Tests Locally

Run full test suite:

```bash
pytest tests/ -v
```

Run agent harness only:

```bash
pytest tests/agent_harness/ -v
```

Run fast tests only (skip e2e and harness):

```bash
pytest tests/ -m "not e2e and not agent_harness" -q
```

## Lint / Format / Type Check

Lint:

```bash
ruff check . --fix
```

Format:

```bash
ruff format .
```

Type check:

```bash
mypy --strict pycodex/
```

## Full Quality Gate (CI Parity)

```bash
ruff check . --fix
ruff format . --check
mypy --strict pycodex/
pytest tests/ -v
pytest tests/agent_harness/ -v
```

## Pre-commit Hooks

Install hooks:

```bash
pre-commit install
pre-commit install -t pre-push
```

Run hooks on all files:

```bash
PRE_COMMIT_HOME=.pre-commit-cache pre-commit run --all-files
```

## CI

GitHub Actions workflow:

- `.github/workflows/ci.yml`

It runs on push and pull request with:

- Ruff lint
- Ruff format check
- Mypy strict
- Full pytest suite
- Agent harness tests

