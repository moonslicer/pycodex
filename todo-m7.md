# Milestone 7 TODO — Context Lifecycle Foundation

## Goal
Stabilize long-running session behavior by completing context/state fundamentals before persistence (M8):
1. finalize token accounting (per-turn + cumulative),
2. add a pluggable auto-compaction interface (strategy + implementation) with deterministic defaults and a locked summary block format,
3. add global user config (`~/.pycodex/config.toml`) with clear precedence,
4. harden local resiliency for subprocess failures/timeouts and Ctrl+C interruption.

## Architecture
```
ModelClient.stream()
  └─ emits Completed(usage=input/output)
        ↓
Agent.run_turn()
  ├─ computes per-turn usage
  ├─ updates cumulative session usage
  ├─ emits turn.completed.usage (stable shape)
  └─ invokes CompactionOrchestrator
        ↓
CompactionOrchestrator
  ├─ CompactionStrategy.plan(context) -> CompactionPlan | None
  ├─ CompactionImplementation.summarize(request) -> SummaryOutput
  └─ apply summary block replacement to Session
        ↓
Session (history + cumulative usage totals)
```

## Locked M7 Contracts (must be stable before M8)
- `turn.completed.usage` must include deterministic per-turn token counts and cumulative totals.
- Compaction summary block format must be finalized in M7 and not drift in M8.
- Compaction trigger semantics must be config-driven (`compaction_threshold_ratio`).
- Strategy/implementation metadata must be carried outside summary text so experiments do not alter summary block schema.

## In Scope
- `pycodex/core/agent.py`
- `pycodex/core/model_client.py`
- `pycodex/core/session.py`
- `pycodex/core/compaction.py` (new compaction interfaces/orchestration)
- `pycodex/core/config.py`
- `pycodex/core/event_adapter.py` (if usage payload shape changes)
- `pycodex/protocol/events.py` (if usage schema changes)
- `pycodex/__main__.py` (runtime/interrupt wiring as needed)
- `pycodex/tools/shell.py` (timeout/hang handling hardening as needed)
- `tests/core/test_token_usage.py` (new)
- `tests/core/test_compaction.py` (new)
- `tests/core/test_compaction_registry.py` (new)
- `tests/core/test_config.py` (extend: global config layer)
- `tests/e2e/test_cli_tool_failures.py` (extend)
- `tests/e2e/test_interrupts.py` (new)

## Out of Scope
- Session persistence/resume and JSONL ledger (M8)
- Planner persistence (M9 planner remains ephemeral)
- Network tool resiliency (M10)
- Transport/runtime multi-client migration (M11)

## Success Metrics

### Functional
- Long multi-turn sessions auto-compact before context exhaustion.
- `turn.completed` events expose reliable token usage each turn.
- Cumulative token totals are available from session state and remain monotonic.
- Ctrl+C cleanly interrupts active turns in text and JSON modes.

### Contract / Architecture
- Compaction is triggered only by configured threshold policy, not ad-hoc heuristics.
- Compaction summary block shape is deterministic for equivalent input history.
- Config precedence is enforced: CLI > env > project `pycodex.toml` > global `~/.pycodex/config.toml` > defaults.

### Quality Gates
- `.venv/bin/ruff check . --fix`
- `.venv/bin/ruff format .`
- `.venv/bin/mypy --strict pycodex/`
- `.venv/bin/pytest tests/ -v`

## TODO Tasks

- [x] T1: Token accounting contract finalization (`core/model_client.py`, `core/agent.py`, `core/session.py`)
  - Ensure model usage extraction is robust and type-safe.
  - Emit per-turn usage and update cumulative session totals in one ownership path.
  - Finalize `turn.completed.usage` payload shape (explicit turn + cumulative fields).
  - Add regression tests for missing/invalid usage payloads and monotonic cumulative totals.
  - Verify:
    - `.venv/bin/pytest tests/core/test_token_usage.py -q`

- [x] T2: Compaction interfaces + default implementations (`core/compaction.py`, `core/agent.py`, `core/session.py`)
  - Define interface split:
    - `CompactionStrategy` decides trigger/range (`plan(...)`),
    - `CompactionImplementation` generates summary (`summarize(...)`).
  - Add default components:
    - `threshold_v1` strategy (remaining-context-ratio based),
    - `local_summary_v1` implementation (deterministic local summarization path).
  - Add orchestrator that runs plan -> summarize -> apply.
  - Replace compacted history range with a single stable summary block.
  - Guarantee idempotent behavior when compaction runs repeatedly in long sessions.
  - Verify:
    - `.venv/bin/pytest tests/core/test_compaction.py -q`
    - `.venv/bin/pytest tests/core/test_compaction_registry.py -q`

- [x] T3: Config plumbing for compaction and policy defaults (`core/config.py`, `__main__.py`)
  - Add `compaction_threshold_ratio: float = 0.2`.
  - Add `compaction_strategy` and `compaction_implementation` selectors (defaults: `threshold_v1`, `local_summary_v1`).
  - Add optional compaction strategy/implementation options mapping.
  - Add global config file loading from `~/.pycodex/config.toml`.
  - Ensure `default_approval_policy` and `default_sandbox_policy` can be set globally.
  - Enforce precedence: CLI > env > project > global > defaults.
  - Verify:
    - `.venv/bin/pytest tests/core/test_config.py -k global_config -q`

- [x] T4: Local resiliency hardening (`core/model_client.py`, `tools/shell.py`, runtime interrupt paths)
  - Harden retry/backoff for transient model API failures.
  - Ensure shell subprocess timeouts terminate hung processes deterministically.
  - Ensure Ctrl+C exits cleanly during active turns in text and JSON modes.
  - Verify:
    - `.venv/bin/pytest tests/e2e/test_cli_tool_failures.py tests/e2e/test_interrupts.py -q`

- [x] T5: Cross-module integration lock-in
  - Add/extend integration tests to cover:
    - token accounting + event emission consistency,
    - compaction strategy/implementation selection and deterministic summary replacement behavior,
    - interrupt behavior during active turn/tool execution.
  - Verify:
    - `.venv/bin/pytest tests/core/test_agent.py tests/e2e/test_cli_json_contract.py -k "usage or compaction or interrupt" -q`

- [ ] T6: Milestone hard gates and manual verification
  - Run full quality gates:
    - `.venv/bin/ruff check . --fix`
    - `.venv/bin/ruff format .`
    - `.venv/bin/mypy --strict pycodex/`
    - `.venv/bin/pytest tests/ -v`
  - Run M7 manual verification:
    - long multi-turn session until compaction triggers,
    - confirm summary block replaced older context,
    - confirm `turn.completed.usage` token totals,
    - confirm Ctrl+C clean shutdown.

## Task Dependency Graph
```
T1 (token accounting) ──> T2 (compaction interfaces + defaults)
T2 ──> T3 (config selection + global defaults)
T2 + T4 + T5 ──> T6 (full gates + manual verification)
```

## Milestone Verification
- `PYCODEX_FAKE_MODEL=1 .venv/bin/python -m pycodex --json "<prompt sequence that forces long context>"` and inspect emitted `turn.completed.usage`.
- `PYCODEX_FAKE_MODEL=1 .venv/bin/python -m pycodex "<long iterative prompt>"` and confirm compaction summary replacement behavior.
- During an active turn, send Ctrl+C and confirm clean exit in text and JSON modes.

## Completion Checklist
- [x] T1 complete
- [x] T2 complete
- [x] T3 complete
- [x] T4 complete
- [x] T5 complete
- [ ] T6 complete
- [ ] Compaction summary block format locked and documented
- [ ] Default compaction strategy/implementation shipped and configurable by name
- [ ] All quality gates pass
- [ ] Manual M7 verification passes (or blockers documented)
