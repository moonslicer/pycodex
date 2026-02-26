# pycodex/cli — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## Separation of Concerns
- The CLI layer contains **no business logic** — only rendering and input handling.
- `app.py` is the only file that reads CLI arguments (`typer` decorators live here only).
- `display.py` is the only file that formats output for the terminal — `tui.py` and `app.py` call display functions; they do not format strings themselves.
- `tui.py` is the only file that manages Textual widgets and the TUI event loop.

## Event Rendering
- The TUI receives `ThreadEvent` objects from the agent core via an async queue — it never calls the agent directly.
- Streaming text (character-by-character) is driven by `OutputTextDelta` events — the TUI does not poll the agent.
- All approval prompts in interactive mode open the `ApprovalModal` widget — never use `input()` in TUI mode.

## Modes
- Three modes, each handled cleanly:
  1. No args → interactive TUI mode (`tui.py`)
  2. `-p "prompt"` → single-turn non-interactive mode (print result, exit)
  3. `--json` → JSONL mode (emit one JSON line per event to stdout)
- Mode selection happens in `app.py`; downstream code does not check the mode.

## Error Display
- All errors shown to the user must go through `display.py` render functions — no raw `print()` in CLI files except in `app.py`'s top-level exception handler.
