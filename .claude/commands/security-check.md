Scan for security vulnerabilities: dependency CVEs, static analysis, subprocess risks, and secrets.

---

## Step 1 — Determine scan scope

- Run `git diff --name-only HEAD` to identify changed files
- Categorize changes:
  - `pyproject.toml` changed → **dependency audit required**
  - Files under `pycodex/tools/` or `pycodex/approval/` changed → **orchestration audit required**
  - Any `.py` file changed → **static analysis required**
  - No Python files changed → report `SKIP — no Python changes` and stop

## Step 2 — Dependency audit

- Run: `.venv/bin/python -m pip_audit`
- If module import fails, install dev tools in the project venv and retry:
  - `.venv/bin/python -m pip install -e '.[dev]'`
- If install fails, report: `FAIL — dependency audit unavailable (pip-audit install failed)`
- Parse output for vulnerabilities at any severity
- For each finding: report CVE ID, package, installed version, fixed version
- If CRITICAL or HIGH severity found: mark as **FAIL**

## Step 3 — Static security analysis

- Run: `.venv/bin/python -m bandit -r pycodex/ -ll -f json`
- If module import fails, install dev tools in the project venv and retry:
  - `.venv/bin/python -m pip install -e '.[dev]'`
- If install fails, report: `FAIL — static security scan unavailable (bandit install failed)`
- Parse JSON output for issues with severity MEDIUM or HIGH
- Key patterns to watch for this project:
  - `B603` — subprocess without shell=False
  - `B604` — function call with shell=True
  - `B110` — try/except/pass silencing errors
  - `B105/B106/B107` — hardcoded passwords or credentials
- For each finding: report severity, file:line, issue code, description

## Step 4 — Subprocess and injection pattern check

- Search all `.py` files for these patterns:
  - `shell=True` — outside of approved tool files (`tools/shell.py`)
  - `os.system(` — never acceptable
  - `subprocess.call(` or `subprocess.run(` — should use async equivalent
  - `eval(` or `exec(` — never acceptable in production code
  - String formatting in subprocess args (f-strings, .format, %) — injection risk
- For each finding: report file:line, pattern, and why it is risky

## Step 5 — Secrets detection

- Run: `detect-secrets scan --list-all-secrets` or grep for common patterns:
  - `sk-` (OpenAI API keys)
  - `AKIA` (AWS access keys)
  - `ghp_` or `gho_` (GitHub tokens)
  - Hardcoded strings assigned to variables named `*_key`, `*_secret`, `*_token`, `*_password`
- If `detect-secrets` is installed, prefer it; otherwise use grep patterns
- Exclude test fixtures and `.env.example` files from results

## Step 6 — Report

```
**Scan scope**: [files changed since HEAD]
**Checks run**: [dependency audit / static analysis / subprocess patterns / secrets detection]

**Status**: PASS / WARN / FAIL

**FAIL items** (must fix):
- [check] — file:line — severity — description — fix: [suggestion]

**WARN items** (accepted risks — document in docs/ai/memory.md):
- [check] — file:line — description

**Dependency audit**: PASS / N vulnerabilities found / FAIL (tool unavailable)
**Static analysis**: PASS / N findings / FAIL (tool unavailable)
**Subprocess patterns**: PASS / N findings
**Secrets detection**: PASS / N findings / SKIPPED
```

## Step 7 — Fix and re-scan (if FAIL items exist)

- For each FAIL item: propose a specific fix
- Ask user: "Should I apply these fixes?"
- If approved: implement fixes, then re-run Steps 2-5
- Report delta: "N issues resolved, M remaining"
- Repeat until PASS or user accepts remaining items as WARN
