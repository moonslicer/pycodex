# Milestone 3 TODO — Event Protocol + JSONL Mode

## Goal
Add a stable, serializable event protocol and a `--json` CLI mode:
1. canonical Pydantic schema in `protocol/events.py`,
2. stateful adapter in `core/event_adapter.py` that translates internal `AgentEvent` callbacks to protocol events,
3. token usage surfaced to `turn.completed`,
4. `turn.failed` boundary for unhandled agent-loop exceptions in JSON mode,
5. `--json` flag in `__main__.py` that streams one protocol event per line to stdout.

## Architecture
```
core/agent.py          internal AgentEvent dataclasses (unchanged)
        ↓
core/event_adapter.py  stateful mapper: AgentEvent → ProtocolEvent (new)
        ↓
__main__.py            renderer: text mode or JSONL mode (--json flag)
```
`agent.py` internal types are NOT replaced. The adapter is the permanent translation layer.

## In Scope
- `pycodex/protocol/__init__.py` (new package)
- `pycodex/protocol/events.py` (new schema)
- `pycodex/core/event_adapter.py` (new adapter)
- `pycodex/core/model_client.py` (modify: surface token usage in `Completed`)
- `pycodex/core/agent.py` (modify: thread usage through `TurnCompleted`)
- `pycodex/__main__.py` (modify: `--json` flag + `turn.failed` boundary)
- `tests/protocol/test_events.py`
- `tests/core/test_event_adapter.py`
- `tests/core/test_model_client.py` (extend: usage assertions)
- `tests/core/test_agent.py` (extend: usage threading assertions)
- `tests/test_main.py` (extend: `--json` flag + `turn.failed` assertions)

## Out of Scope
- `item.updated` streaming delta events (M4 — TUI needs it)
- Schema versioning or backward-compatibility guarantees
- Event replay, persistence, or session recovery (M6)
- WebSocket or SSE transport — JSONL stdout only
- Parallel tool dispatch — sequential ordering unchanged
- Interactive TUI (M4)
- Sandboxing (M5)

## Success Metrics

### Functional
- `python3 -m pycodex --json "what is 2+2"` emits valid JSONL; every line has a root `type` field.
- `python3 -m pycodex --json "what is 2+2" | python3 -c "import sys,json; [print(json.loads(l)['type']) for l in sys.stdin]"` prints event types without error.
- A tool-call turn emits `item.started` and `item.completed` with the same `item_id` (= tool `call_id`).
- `turn.failed` is emitted on unhandled agent-loop exception in `--json` mode; process exits non-zero.
- `turn.completed` contains `usage` when the Responses API returns it; `usage` is `null`/absent otherwise.
- ABORT path emits `turn.completed` (not `turn.failed`) — intentional user action is not a failure.
- Human text mode (`python3 -m pycodex "..."`) is unchanged; adapter is not instantiated in text mode.

### Architecture / Contract
- `agent.py` internal event types (`TurnStarted`, `ToolCallDispatched`, etc.) are NOT modified structurally.
- Adapter owns all ID generation: `thread_id` injectable (default `uuid4()`), `turn_id` monotonic counter (`turn_1`, `turn_2`, …), `item_id` = `call_id` with `item_<turn>_<ordinal>` fallback.
- Adapter is stateful per-run; no module-level mutable state.
- Human CLI output and JSONL processor are separate code paths — no shared formatter.
- Schema models use `model_config = ConfigDict(frozen=True)`.
- Item payload uses `item_kind` discriminator (not `type`) to avoid collision with root event `type`.

### Quality Gates
- `ruff check . --fix`
- `ruff format .`
- `mypy --strict pycodex/`
- `pytest tests/ -v`

### Milestone Verification
- `python3 -m pycodex --json "what is 2+2" | python3 -c "import sys,json; [print(json.loads(l)['type']) for l in sys.stdin]"`

## Vertical Verifiable Flow (Thin Slice)
1. CLI parses `--json`; builds adapter with fixed `thread_id` for test reproducibility.
2. `thread.started` emitted immediately; serialized to stdout line 1.
3. Agent starts turn → adapter receives `TurnStarted` → emits `turn.started` (line 2).
4. Model returns a tool call → `ToolCallDispatched(call_id="call_1", name="shell", …)` → adapter emits `item.started(item_id="call_1", item_kind="tool_call")` (line 3).
5. Tool executes → `ToolResultReceived(call_id="call_1", …)` → adapter emits `item.completed(item_id="call_1", item_kind="tool_result")` (line 4) — same `item_id`.
6. Model returns final text → `TurnCompleted(final_text=…, usage=…)` → adapter emits `turn.completed` with optional `usage` (line 5).
7. Each line is `model.model_dump_json()` with root `type` field.

## TODO Tasks

- [x] T1: `protocol/__init__.py` + `protocol/events.py` — schema + serialization contract
  - Create `pycodex/protocol/__init__.py` (empty, marks package).
  - Define frozen Pydantic models for all six event types, each with a `type: Literal[…]` root discriminator:
    - `ThreadStarted` (`type="thread.started"`, `thread_id: str`)
    - `TurnStarted` (`type="turn.started"`, `thread_id: str`, `turn_id: str`)
    - `TurnCompleted` (`type="turn.completed"`, `thread_id: str`, `turn_id: str`, `final_text: str`, `usage: TokenUsage | None = None`)
    - `TurnFailed` (`type="turn.failed"`, `thread_id: str`, `turn_id: str`, `error: str`)
    - `ItemStarted` (`type="item.started"`, `thread_id: str`, `turn_id: str`, `item_id: str`, `item_kind: Literal["tool_call", "assistant_message"]`, `name: str | None = None`, `arguments: str | None = None`)
    - `ItemCompleted` (`type="item.completed"`, `thread_id: str`, `turn_id: str`, `item_id: str`, `item_kind: Literal["tool_result", "assistant_message"]`, `content: str`)
  - `TokenUsage`: `input_tokens: int`, `output_tokens: int` (frozen Pydantic model).
  - `ProtocolEvent = Annotated[ThreadStarted | TurnStarted | TurnCompleted | TurnFailed | ItemStarted | ItemCompleted, Field(discriminator="type")]`
  - All models: `model_config = ConfigDict(frozen=True)`.
  - Tests (`tests/protocol/test_events.py`):
    - Each model round-trips through `model_dump_json()` → `model_validate_json()`.
    - Discriminated union resolves correct type from raw JSON for each event type.
    - `TokenUsage` validates int fields; rejects strings.
    - `item_kind` accepts only declared literals; rejects unknown values.
    - `ProtocolEvent` union rejects unknown `type` value.
  - Verify: `pytest tests/protocol/test_events.py -v`

- [x] T2: `core/event_adapter.py` — stateful internal→protocol mapper + ID strategy
  - Class `EventAdapter`:
    - Constructor: `thread_id: str = field(default_factory=lambda: str(uuid4()))`, `_turn_counter: int = 0`, `_item_counter: int = 0`, `_inflight: dict[str, str]` (call_id → item_id).
    - `on_agent_event(event: AgentEvent) -> list[ProtocolEvent]`: synchronous, returns ordered list of protocol events produced.
    - ID rules:
      - `turn_id` = `f"turn_{self._turn_counter}"` (increment on each `TurnStarted`).
      - `item_id` = `call_id` from `ToolCallDispatched` if non-empty; else `f"item_{self._turn_id}_{self._item_counter}"`.
      - Store `call_id → item_id` in `_inflight`; look up on `ToolResultReceived`; remove after `item.completed` emitted.
    - Mapping rules (exact):
      - `TurnStarted` → `[TurnStarted(…)]` (increment turn counter first)
      - `ToolCallDispatched` → `[ItemStarted(item_kind="tool_call", name=…, arguments=…)]`
      - `ToolResultReceived` → `[ItemCompleted(item_kind="tool_result", content=result)]`
      - `TurnCompleted` → `[TurnCompleted(final_text=…, usage=…)]`
    - ABORT: agent emits `TurnCompleted` on abort (no exception); adapter maps it to `turn.completed` — no special handling needed.
    - `thread.started` is emitted once by the caller at startup (not by the adapter per-turn).
  - Tests (`tests/core/test_event_adapter.py`):
    - `test_id_generation_and_reuse`: `ToolCallDispatched(call_id="call_abc")` → `ItemStarted(item_id="call_abc")`; `ToolResultReceived(call_id="call_abc")` → `ItemCompleted(item_id="call_abc")`. Same ID both sides.
    - `test_id_fallback_when_call_id_empty`: `call_id=""` → synthesized `item_id` matches pattern `item_turn_1_1`.
    - `test_no_tool_turn`: `TurnStarted` + `TurnCompleted` → exactly `[turn.started, turn.completed]`; no item events.
    - `test_single_tool_call_turn`: `TurnStarted` + `ToolCallDispatched` + `ToolResultReceived` + `TurnCompleted` → `[turn.started, item.started, item.completed, turn.completed]` in that order.
    - `test_multi_tool_call_turn`: two consecutive tool calls in one turn → two `item.started` + two `item.completed` with distinct IDs; `item.started` for call 2 comes after `item.completed` for call 1 (sequential).
    - `test_turn_counter_increments`: two sequential turns → `turn_id` values are `turn_1`, `turn_2`.
    - `test_abort_turn_emits_turn_completed_not_failed`: simulate abort by emitting `TurnCompleted` directly (as agent does on abort) → adapter emits `turn.completed`.
    - `test_injectable_thread_id`: construct adapter with explicit `thread_id="test-thread-1"` → all emitted events carry that ID.
  - Verify: `pytest tests/core/test_event_adapter.py -v`

- [ ] T3: `core/model_client.py` + `core/agent.py` — surface token usage through to `TurnCompleted`
  - Investigate `Completed` event in `model_client.py`: check whether `response.usage` is available on the Responses API stream completion object.
  - If available: add `usage: dict[str, int] | None` to the `Completed` dataclass; populate from `response.usage` (keys: `input_tokens`, `output_tokens`).
  - If not available: add the field defaulting to `None` and document the gap with a `# TODO` comment.
  - Extend `core/agent.py` `TurnCompleted` dataclass: add `usage: dict[str, int] | None = None`; populate from the `Completed` stream event when non-None.
  - Adapter maps `TurnCompleted.usage` → `TokenUsage(input_tokens=…, output_tokens=…)` if present; else `usage=None` on `turn.completed`.
  - Tests:
    - `tests/core/test_model_client.py`: extend existing mock to return a `Completed` with fake usage `{"input_tokens": 10, "output_tokens": 5}`; assert `Completed.usage == {"input_tokens": 10, "output_tokens": 5}`.
    - `tests/core/test_model_client.py`: when usage absent from mock response, assert `Completed.usage is None`.
    - `tests/core/test_agent.py`: mock `Completed` with usage → assert `TurnCompleted.usage == {"input_tokens": 10, "output_tokens": 5}` via event callback.
    - `tests/core/test_event_adapter.py`: `test_usage_in_turn_completed` — adapter receives `TurnCompleted(usage={"input_tokens":10,"output_tokens":5})` → emits `turn.completed` with `usage=TokenUsage(input_tokens=10, output_tokens=5)`.
    - `tests/core/test_event_adapter.py`: `test_usage_none_when_absent` — adapter receives `TurnCompleted(usage=None)` → `turn.completed.usage is None`.
  - Verify: `pytest tests/core/test_model_client.py tests/core/test_agent.py tests/core/test_event_adapter.py -k usage -v`

- [ ] T4: `__main__.py` — `--json` flag, adapter wiring, `turn.failed` exception boundary
  - Add `--json` boolean flag (default `False`).
  - In JSON mode:
    - Instantiate `EventAdapter`; emit `ThreadStarted` immediately (before agent turn) and serialize to stdout.
    - Wire `adapter.on_agent_event` as the `on_event` callback to `run_turn()`.
    - Serialize each returned `ProtocolEvent` via `event.model_dump_json()` + `"\n"` to stdout.
    - Wrap turn execution in a `try/except Exception`: on unhandled exception, serialize one `TurnFailed(error=str(e))` event to stdout, then exit with code 1.
    - `turn.failed` uses current `thread_id` and `turn_id` from adapter state.
  - In text mode: adapter is NOT instantiated; existing human-readable output path is unchanged.
  - Human text formatter and JSONL path share no output code.
  - Tests (`tests/test_main.py` extensions):
    - `test_json_flag_emits_valid_jsonl`: mock agent turn (no-tool); assert stdout is line-delimited, each line parses as JSON, every line has `type` key.
    - `test_json_flag_event_ordering`: mock single tool-call turn; assert event type sequence is `["thread.started", "turn.started", "item.started", "item.completed", "turn.completed"]`.
    - `test_json_flag_turn_failed_on_exception`: mock agent turn that raises `RuntimeError("boom")`; assert last stdout line is `turn.failed` with `error` containing `"boom"`; process exit code is 1.
    - `test_text_mode_unchanged`: no `--json` flag; assert stdout does not contain JSON lines; assert existing text output behavior is preserved.
  - Verify: `pytest tests/test_main.py -k json -v`

- [ ] T5: Quality gates + milestone verification
  - Run `ruff check . --fix` — must be clean.
  - Run `ruff format .` — must be clean.
  - Run `mypy --strict pycodex/` — must pass on all source files including `protocol/` and `core/event_adapter.py`.
  - Run `pytest tests/ -v` — all tests pass; count vs M2 baseline (141 passed) must increase.
  - Record gate results and new test count in completion checklist below.
  - Verify: `python3 -m pycodex --json "what is 2+2" | python3 -c "import sys,json; [print(json.loads(l)['type']) for l in sys.stdin]"` (requires local OpenAI endpoint).

## Completion Checklist
- [ ] All T1–T5 done
- [ ] Quality gates all pass (`ruff check`, `ruff format`, `mypy --strict`, `pytest tests/ -v`)
- [ ] Milestone verification command passes (or blocked by local runtime — document if so)
- [ ] Milestone report includes: files changed, gate results, verification output, risks/assumptions, next milestone recommendation
