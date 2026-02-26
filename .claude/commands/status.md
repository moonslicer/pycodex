Report the current build status of pycodex.

Steps:
1. Read `engineering-plan.md` to get the full list of milestones and their required files
2. Check which source files exist under `pycodex/` to determine completed milestones
3. Run quality gates on existing code:
   - `ruff check .`
   - `mypy --strict pycodex/` (if any source files exist)
   - `pytest tests/ -v` (if any tests exist)

Report format:

**Milestones**
- M1: [DONE | IN PROGRESS | NOT STARTED] — list missing files if in progress
- M2: ...
- M3: ...
- M4: ...
- M5: ...
- M6: ...

**Current milestone**: M? — [name]
**Next to build**: M? — [name]

**Quality gates** (on existing code)
- ruff: PASS / FAIL
- mypy: PASS / FAIL
- pytest: PASS / FAIL (N tests)

**Blockers**: any known issues preventing the next milestone from starting
