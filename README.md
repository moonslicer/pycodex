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
pip install ruff mypy pytest pytest-asyncio pydantic pre-commit bandit pip-audit
pip install openai
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

## Local Review Command

Run one local command for the standard review checks:

```bash
make review
```

By default this uses `.venv/bin/python` for Python tooling. If needed, override it:

```bash
make review PYTHON=python3
```

This runs:

- Python: `ruff check . --fix`, `ruff format . --check`, `mypy --strict pycodex/`, `pytest tests/ --ignore=tests/agent_harness -m "not e2e" -v`
- TUI: `npm --prefix tui run typecheck`, `npm --prefix tui run lint`, `npm --prefix tui test -- --runInBand --passWithNoTests`

Optional local hygiene checks:

```bash
make hygiene
```

This runs:

- `knip` via `npx` for unused TypeScript exports/dependencies (`tui`)
- `jscpd` via `npx` for duplication scan across `tui/src`, `pycodex`, and `tests`

To run everything together:

```bash
make review-hygiene
```

## Local Default Gate

```bash
ruff check . --fix
ruff format . --check
mypy --strict pycodex/
pytest tests/ --ignore=tests/agent_harness -m "not e2e" -v
pytest tests/agent_harness/ -v
```

## CI-Complete Gate (Parity)

Run this when you need close parity with `.github/workflows/ci.yml`:

```bash
# Python checks
ruff check .
ruff format . --check
mypy --strict pycodex/
pytest tests/ --ignore=tests/agent_harness -m "not e2e" -v
pytest tests/agent_harness/ -v
pip-audit
bandit -r pycodex/ -ll -q

# TUI checks
cd tui
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

Optional (matches CI behavior only for pull requests targeting `main`):

```bash
pytest tests/ -m "e2e" -v
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

- Gitleaks secret scan (full git history)
- Absolute-path guard (`/Users/*`, `/home/*`, `C:\Users\*`)
- Ruff lint
- Ruff format check
- Mypy strict
- Pytest unit+integration (`not e2e`, harness excluded)
- Agent harness tests
- Dependency audit (`pip-audit`)
- Security scan (`bandit`)
- TUI checks (`npm run typecheck`, `npm run lint`, `npm test`, `npm run build`)
- E2E tests on pull requests targeting `main`
