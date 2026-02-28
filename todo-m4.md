# Milestone 4 TODO — Interactive Terminal UI

## Goal
Build a TypeScript + Ink interactive terminal UI that drives the Python agent over stdio with a typed protocol boundary:
1. establish a strict TypeScript protocol/toolchain foundation (M4A),
2. implement Python `--tui-mode` bridge + minimal multi-turn Ink shell (M4B),
3. add streaming assistant deltas via `item.updated` (M4C),
4. add approval modal request/response flow (M4D),
5. add tool-call panels, status polish, and interrupt UX (M4E),
6. keep existing text mode and `--json` mode contracts unchanged.

## Architecture
```
TypeScript (tui/src/index.ts)         Python (pycodex)
--------------------------------      --------------------------------------
spawn python -m pycodex --tui-mode    __main__.py mode dispatch
stdin  <- JSON-RPC commands           core/tui_bridge.py command loop
stdout -> JSONL ProtocolEvents        core/event_adapter.py + protocol/events.py

React + Ink app
  hooks: event -> state reducers
  components: rendering + key input
  protocol layer: transport boundary only
```

`pycodex/core/agent.py` remains the source of truth for agent behavior.
TUI is orchestration and rendering only.

## In Scope
- `tui/package.json` (new)
- `tui/tsconfig.json` (new)
- `tui/jest.config.ts` (new)
- `tui/eslint.config.js` (new)
- `tui/src/protocol/types.ts` (new)
- `tui/src/protocol/reader.ts` (new)
- `tui/src/protocol/writer.ts` (new)
- `tui/src/protocol/transports/stdio.ts` (new)
- `tui/src/index.ts` (new)
- `tui/src/app.tsx` (new)
- `tui/src/hooks/useProtocolEvents.ts` (new)
- `tui/src/hooks/useTurns.ts` (new)
- `tui/src/hooks/useLineBuffer.ts` (new)
- `tui/src/hooks/useApprovalQueue.ts` (new)
- `tui/src/components/ChatView.tsx` (new)
- `tui/src/components/InputArea.tsx` (new)
- `tui/src/components/StatusBar.tsx` (new)
- `tui/src/components/Spinner.tsx` (new)
- `tui/src/components/ApprovalModal.tsx` (new)
- `tui/src/components/ToolCallPanel.tsx` (new)
- `tui/src/__tests__/reader.test.ts` (new)
- `tui/src/__tests__/writer.test.ts` (new)
- `tui/src/__tests__/useTurns.test.ts` (new)
- `tui/src/__tests__/useLineBuffer.test.ts` (new)
- `tui/src/__tests__/useApprovalQueue.test.ts` (new)
- `tui/src/__tests__/app.test.tsx` (new)
- `tui/src/__tests__/approvalModal.test.tsx` (new)
- `tui/src/__tests__/toolCallPanel.test.tsx` (new)
- `tui/src/__tests__/statusBar.test.tsx` (new)
- `tui/src/__tests__/chatView.test.tsx` (new)
- `tui/src/__tests__/inputArea.test.tsx` (new)
- `pycodex/core/tui_bridge.py` (new)
- `pycodex/__main__.py` (modify: add `--tui-mode`)
- `pycodex/protocol/events.py` (modify: add `ItemUpdated`, `ApprovalRequested`)
- `pycodex/core/agent.py` (modify: surface text deltas)
- `pycodex/core/event_adapter.py` (modify: map to `item.updated`)
- `tests/core/test_tui_bridge.py` (new)
- `tests/protocol/test_events.py` (extend)
- `tests/core/test_event_adapter.py` (extend)
- `tests/test_main.py` (extend)

## Out of Scope
- `tui/src/protocol/transports/websocket.ts` in M4 (deferred to M6)
- session persistence/resume and compaction (M6)
- sandboxing/exec policy changes (M5)
- browser/web frontend
- MCP-specific approval UX
- tool parallel dispatch

## Success Metrics

### Functional
- `node tui/dist/index.js` launches a working multi-turn Ink UI.
- `user.input` starts turns; input is disabled while a turn is active.
- `item.updated` renders streaming output incrementally (newline-gated).
- Mutating actions prompt via `approval.request`/`approval.response` modal flow.
- Ctrl+C / interrupt command cancels active turn and reports interruption cleanly.
- Tool lifecycle (`item.started`/`item.completed`) renders in tool panels.
- Status bar shows token usage from `turn.completed.usage`.
- Existing CLI modes still work:
  - `python3 -m pycodex "..."`
  - `python3 -m pycodex --json "..."`

### Architecture / Contract
- `tui/src/protocol/*` is the only TUI layer touching transport and JSON parsing.
- Unknown event/command payloads are ignored safely (no crash).
- Protocol types remain discriminated unions with exhaustive handling.
- Turn ID for approvals comes from emitted `turn.started` event ID capture.
- Approval `ABORT` preserves current Python contract: maps to protocol `turn.completed` with abort text.
- `turn.failed(error="interrupted")` is reserved for explicit interrupt/cancel paths.

### Quality Gates
Python:
- `ruff check . --fix`
- `ruff format .`
- `mypy --strict pycodex/`
- `pytest tests/ -v`
- `pytest tests/agent_harness/test_smoke.py -v`

TypeScript:
- `cd tui && npm run typecheck`
- `cd tui && npm run lint`
- `cd tui && npm test -- --coverage`
- `cd tui && npm run build`

### Milestone Verification
- `node tui/dist/index.js`
  - Manual scenario: normal question -> mutating action (approval modal) -> interrupt active turn.
- `python3 -m pycodex --json "what is 2+2"`
  - Confirm M3 JSON mode remains valid and unchanged.

## Vertical Verifiable Flow (Thin Slice)
1. M4A: `tui` protocol package compiles/tests without Python changes.
2. M4B: launch TUI, Python emits `thread.started`, user submits prompt, receives `turn.started` -> `turn.completed`.
3. M4C: deltas stream via `item.updated` and render incrementally.
4. M4D: mutating call emits `approval.request`; modal sends `approval.response`; turn resumes.
5. M4E: tool panel lifecycle renders; token usage appears; interrupt path emits interruption outcome and UI remains responsive.

## TODO Tasks

- [x] T1: M4A toolchain scaffold (`tui/package.json`, `tsconfig.json`, `jest.config.ts`, `eslint.config.js`)
  - Enforce strict TS and ESLint 9 flat config.
  - Add scripts: `build`, `dev`, `start`, `typecheck`, `lint`, `test`.
  - Verify:
    - `cd tui && npm install`
    - `cd tui && npm run typecheck`
    - `cd tui && npm run lint`

- [x] T2: M4A protocol contracts + stdio transport
  - Implement `types.ts`, `reader.ts`, `writer.ts`, `transports/stdio.ts`.
  - Reader must ignore malformed JSONL safely.
  - Verify:
    - `cd tui && npm test -- --runInBand --findRelatedTests src/protocol`

- [x] T2.1: M4A stdio transport hardening (error handlers, stderr drain, readline cleanup, jest dist ignore)

- [x] T3: M4A protocol test baseline
  - Add `reader.test.ts` + `writer.test.ts` for command/event shape and line framing.
  - Align TS/Python optional-null contract for `item.started`:
    - Accept `name: null` and `arguments: null` in `tui/src/protocol/types.ts` and stdio validator.
    - Add regression coverage proving a valid `item.started` payload with null optional fields is not dropped.
  - Verify:
    - `cd tui && npm test -- --runInBand --findRelatedTests src/__tests__/reader.test.ts src/__tests__/writer.test.ts`

- [x] T4: M4B Python `--tui-mode` entrypoint wiring
  - Update `pycodex/__main__.py` parser/mode dispatch.
  - Ensure positional prompt text mode and `--json` behavior remain unchanged.
  - Verify:
    - `pytest tests/test_main.py -k "tui or json or prompt" -v`

- [x] T5: M4B add `core/tui_bridge.py` command loop
  - Build runtime dependencies (`Session`, `ModelClient`, `ToolRouter`) with TUI-specific `ask_user_fn` injection via orchestrator.
  - Read stdin JSON-RPC (`user.input`, `approval.response`, `interrupt`) and emit JSONL protocol events.
  - Verify:
    - `pytest tests/core/test_tui_bridge.py -k "user_input or interrupt or unknown or thread_started" -v`

- [x] T6: M4B baseline Ink shell (`index.ts`, `app.tsx`, base components/hooks)
  - Implement multi-turn shell without streaming/approval modal/tool panels.
  - **Build order**: hooks first → `index.ts` entry point → components last.
  - **Spawn**: use `spawn()` not `exec()` — `exec()` buffers stdout and breaks JSONL streaming.
  - **State**: use `useReducer` not `useState` for turn state — avoids stale closure bugs in event handlers.
  - **Stable keys**: always `key={turn.turn_id}`, never `key={index}`.
  - **Single subscription**: `useProtocolEvents` owns the one `reader.onEvent()` call; `useTurns` derives from `lastEvent` — no duplicate subscriptions.
  - **Ctrl+C**: set `exitOnCtrlC: false` in Ink `render()` — app must own Ctrl+C to send `interrupt` before killing process.
  - **Cleanup sequence**: `writer.close()` → `SIGTERM` → 5s timeout → `SIGKILL` — prevents zombie Python processes.
  - **User text**: `TurnState.userText` has no protocol event source; track locally in `app.tsx`, keep empty string in M4B.
  - **Effect cleanup**: always return the `reader.onEvent()` unsubscribe function from `useEffect` cleanup.
  - Keep visible-turn cap behavior and stable keys.
  - Verify:
    - `cd tui && npm test -- --runInBand --findRelatedTests src/app.tsx src/hooks/useTurns.ts`

- [x] T7: M4B smoke + integration stabilization
  - Add one end-to-end app smoke (turn started/completed) and input-disable assertion.
  - Ensure process cleanup/exit handling in `index.ts` is deterministic.
  - Verify:
    - `cd tui && npm run build`
    - `cd tui && npm test -- --runInBand --findRelatedTests src/index.ts src/__tests__/app.test.tsx`

- [x] T8: M4C protocol additions (`item.updated`)
  - Add `ItemUpdated` model in Python events.
  - Emit agent text deltas through callback path and map in adapter.
  - Mirror new union variant in TypeScript protocol types.
  - Verify:
    - `pytest tests/protocol/test_events.py tests/core/test_event_adapter.py -k "updated" -v`

- [x] T9: M4C streaming state reducer + frame-gating
  - Implement `useLineBuffer` reducer (`push`, `flush`, `reset`) and integrate with `useTurns`.
  - Preserve blank lines for committed segments; drop only trailing empty partial at flush end.
  - Add `setImmediate` batching guard in high-rate delta path.
  - Verify:
    - `cd tui && npm test -- --runInBand --findRelatedTests src/hooks/useLineBuffer.ts src/hooks/useTurns.ts`

- [x] T10: M4D protocol addition (`approval.request`) + bridge wait loop
  - Add `ApprovalRequested` model in Python events.
  - In bridge: emit request with captured turn_id, await matching `approval.response` by `request_id`.
  - Verify:
    - `pytest tests/protocol/test_events.py -k "approval" -v`
    - `pytest tests/core/test_tui_bridge.py -k "approval" -v`

- [x] T11: M4D approval queue + modal UI
  - Implement `useApprovalQueue` and `ApprovalModal` (`y/n/s/a`).
  - Disable input while approval queue is non-empty.
  - Verify:
    - `cd tui && npm test -- --runInBand --findRelatedTests src/hooks/useApprovalQueue.ts src/components/ApprovalModal.tsx src/app.tsx`

- [ ] T12: M4E tool panels and status usage polish
  - Implement `ToolCallPanel`; render lifecycle rows keyed by `item_id`.
  - Show latest/cumulative usage in `StatusBar` from `turn.completed.usage`.
  - Verify:
    - `cd tui && npm test -- --runInBand --findRelatedTests src/components/ToolCallPanel.tsx src/components/StatusBar.tsx src/components/ChatView.tsx`

- [ ] T13: M4E interrupt UX completion
  - Ensure Ctrl+C / `interrupt` path cancels active turn and emits interruption outcome once.
  - Keep approval-abort and explicit interrupt semantics distinct.
  - Verify:
    - `pytest tests/core/test_tui_bridge.py -k "interrupt" -v`
    - `cd tui && npm test -- --runInBand --findRelatedTests src/components/InputArea.tsx src/app.tsx`

- [ ] T14: Protocol fallback and contract regression tests
  - Add tests for unknown event/command no-op behavior.
  - Add regression checks for abort mapping to `turn.completed` vs interrupt mapping to `turn.failed`.
  - Verify:
    - `pytest tests/core/test_tui_bridge.py tests/core/test_event_adapter.py tests/test_main.py -k "abort or interrupt or unknown" -v`
    - `cd tui && npm test -- --runInBand --findRelatedTests src/hooks/useTurns.ts src/protocol`

- [ ] T15: Run full milestone gates
  - Python:
    - `ruff check . --fix`
    - `ruff format .`
    - `mypy --strict pycodex/`
    - `pytest tests/ -v`
    - `pytest tests/agent_harness/test_smoke.py -v`
  - TypeScript:
    - `cd tui && npm run typecheck`
    - `cd tui && npm run lint`
    - `cd tui && npm test -- --coverage`
    - `cd tui && npm run build`

- [ ] T16: Run milestone verification and capture output
  - `node tui/dist/index.js` manual run covering normal, approval, and interrupt flows.
  - `python3 -m pycodex --json "what is 2+2"` contract sanity check.

## Completion Checklist
- [ ] All T1–T16 complete
- [ ] M4A done criteria met
- [ ] M4B done criteria met
- [ ] M4C done criteria met
- [ ] M4D done criteria met
- [ ] M4E done criteria met
- [ ] Python gates pass (`ruff`, `format`, `mypy`, `pytest`, harness smoke)
- [ ] TypeScript gates pass (`typecheck`, `lint`, `test`, `build`)
- [ ] Milestone verification commands succeed
- [ ] Completion report includes:
  - files changed,
  - gate outcomes,
  - verification output,
  - risks/assumptions,
  - next milestone recommendation (M5).

## Risks / Assumptions
- `asyncio.CancelledError` is `BaseException`; cancellation handling must be explicit.
- `--tui-mode` parser changes must not regress existing prompt-required flows in other modes.
- ESM + ts-jest + Ink may require `transformIgnorePatterns` maintenance.
- TUI shutdown must avoid orphan Python processes.
- Approval queue must remain FIFO and `request_id`-exact.
