Run all quality gates and report results.

Run in order:
1. `ruff check . --fix`
2. `ruff format .`
3. `mypy --strict pycodex/`
4. `pytest tests/ -v`

Report format:
- **ruff check**: PASS or FAIL (N errors, list file:line for each)
- **ruff format**: PASS or FAIL (N files reformatted)
- **mypy**: PASS or FAIL (N errors, list file:line:message for each)
- **pytest**: PASS or FAIL (N passed, N failed; list failed test name + assertion message)
- **Overall**: All green ✓ or X gates failing

If all pass: "All quality gates green."
If any fail: list only the failures with enough context to fix them directly (file, line, message). Do not list passing checks verbosely.
