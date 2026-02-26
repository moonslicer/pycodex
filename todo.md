# Milestone 1 TODO - Minimal Agent Loop (Non-Interactive)

## Goal
Build a runnable `python -m pycodex "<prompt>"` flow that:
1. sends user input to the model,
2. handles tool calls (`shell`, `read_file`),
3. loops until no tool calls remain,
4. prints the final answer.

## In Scope
- `pycodex/core/config.py`
- `pycodex/core/model_client.py`
- `pycodex/core/session.py`
- `pycodex/tools/base.py`
- `pycodex/tools/shell.py`
- `pycodex/tools/read_file.py`
- `pycodex/core/agent.py`
- `pycodex/__main__.py`

## Out of Scope
- Approval prompts/policies
- Sandboxing
- JSONL event protocol
- Interactive TUI

## Success Metrics

### Functional
- `python3 -m pycodex "list the Python files in the current directory"` runs end-to-end.
- Agent executes tool calls and feeds tool results back into the next model turn.
- Turn exits only when model returns no tool calls.

### Architecture/Contract
- Agent loop is async end-to-end (no blocking calls).
- `Session` is the only history mutator.
- `Session.to_prompt()` returns a copy (no shared mutable history leaks).
- `model_client` yields typed event dataclasses, not raw dicts.
- Tool failures return strings prefixed with `[ERROR]`.

### Quality Gates
- `ruff check . --fix`
- `ruff format .`
- `mypy --strict pycodex/`
- `pytest tests/ -v`

### Milestone Verification
- `python3 -m pycodex "list the Python files in the current directory"`

## Vertical Verifiable Flow (Thin Slice)
1. CLI entrypoint receives prompt.
2. Config + Session + ToolRegistry initialized.
3. `run_turn()` appends user message.
4. Model stream yields text/tool-call events.
5. Tool calls dispatched (`shell`/`read_file`) and results captured.
6. Tool results appended to session.
7. Loop repeats from model sampling.
8. No tool calls -> final text returned/printed.

## TODO Tasks (Dependency-Flexible DAG)

- [x] T1: `core/config.py`
  - Implement `Config` + loader from env/optional `pycodex.toml`.
  - Verify: `python3 -c "from pycodex.core.config import load_config; print(type(load_config()).__name__)"`

- [x] T2: `core/session.py`
  - Implement `Session.append_user_message`, `append_tool_result`, `to_prompt`.
  - Depends on: T1
  - Verify: `python3 -c "from pycodex.core.session import Session; s=Session(); s.append_user_message('hi'); print(len(s.to_prompt()))"`

- [x] T3: `tools/base.py`
  - Implement `ToolHandler` protocol, `ToolRegistry`, `ToolRouter`.
  - Verify: `python3 -c "from pycodex.tools.base import ToolRegistry; print(ToolRegistry().tool_specs())"`

- [ ] T4: `tools/shell.py`
  - Async subprocess tool with timeout + formatted output.
  - Return `[ERROR] ...` on failure.
  - Depends on: T3
  - Verify: `python3 -c "import asyncio; from pathlib import Path; from pycodex.tools.shell import ShellTool; print(asyncio.run(ShellTool().handle({'command':'echo hi'}, Path('.'))))"`

- [ ] T5: `tools/read_file.py`
  - Read file with line numbers + optional offset/limit.
  - Return `[ERROR] ...` on failures.
  - Depends on: T3
  - Verify: temp-file read smoke check.

- [ ] T6: `core/model_client.py`
  - Async streaming client with typed events + one transient reconnect.
  - Depends on: T1
  - Verify: dataclass instantiation/import smoke check.

- [ ] T7: `core/agent.py`
  - Implement async tool-loop orchestration:
    - append user message
    - stream model response
    - execute tool calls
    - append tool results
    - repeat until no tool calls
  - Depends on: T2, T3, T4, T5, T6
  - Verify: coroutine function + local fake-client loop test.

- [ ] T8: `__main__.py`
  - Parse CLI prompt and run `run_turn`.
  - Depends on: T7
  - Verify: `python3 -m pycodex --help`

## Completion Checklist
- [ ] All T1-T8 done
- [ ] Quality gates all pass
- [ ] Milestone verification command passes
- [ ] Milestone report includes risks, assumptions, and next milestone recommendation
