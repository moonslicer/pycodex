Stage and commit current changes with a conventional commit message.

Steps:
1. Run `git status` to see all changed and untracked files
2. Run `git diff --stat` to understand the scope of changes
3. Determine the commit type based on what changed:
   - `feat` — new functionality
   - `fix` — bug fix
   - `refactor` — restructuring without behavior change
   - `test` — adding or updating tests
   - `chore` — tooling, config, deps
   - `docs` — documentation only
4. Determine scope from the primary module changed (e.g., `core`, `tools`, `approval`, `cli`)
5. Stage relevant files — exclude `.DS_Store`, `__pycache__/`, `.env`, `*.pyc`
6. Write and execute the commit:
   - Subject: `<type>(<scope>): <short imperative description>` (≤72 chars)
   - Body (if non-trivial): what changed and why, not how
7. Report: commit hash, full message, and list of staged files

Do not push unless explicitly asked.
Do not amend previous commits — always create a new commit.
