.PHONY: review review-python review-tui hygiene hygiene-knip hygiene-dup review-hygiene

PYTHON ?= .venv/bin/python
RUFF = $(PYTHON) -m ruff
MYPY = $(PYTHON) -m mypy
PYTEST = $(PYTHON) -m pytest

review: review-python review-tui

review-hygiene: review hygiene

review-python:
	$(RUFF) check . --fix
	$(RUFF) format . --check
	$(MYPY) --strict pycodex/
	$(PYTEST) tests/ --ignore=tests/agent_harness -m "not e2e" -v

review-tui:
	npm --prefix tui run typecheck
	npm --prefix tui run lint
	npm --prefix tui test -- --runInBand --passWithNoTests

hygiene: hygiene-knip hygiene-dup

hygiene-knip:
	npx --yes --package=knip knip --directory tui --reporter compact --no-exit-code

hygiene-dup:
	npx --yes --package=jscpd jscpd tui/src pycodex tests --silent --reporters console --min-lines 10 --min-tokens 80 --threshold 100 --format typescript,tsx,python --ignore "**/node_modules/**,**/dist/**,**/.venv/**,**/.git/**"
