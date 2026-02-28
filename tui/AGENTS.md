# tui — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## Scope
- This module owns the TypeScript terminal UI (React + Ink) and transport adapters.
- Python remains the agent brain; TUI code must not reimplement agent, tool, approval, or policy logic.

## Architecture Boundaries
- Keep `src/index.ts` as process/transport wiring only (spawn child, lifecycle, shutdown).
- Keep `src/app.tsx` as orchestration/composition only (wiring hooks to components).
- Keep `src/components/*` presentational and input-focused; no protocol parsing or transport I/O.
- Keep `src/hooks/*` as the single place for state transitions and event-to-state mapping.
- Keep `src/protocol/*` as the only transport/protocol boundary. UI code must never touch raw `stdin/stdout` objects.

## TypeScript Standards
- TypeScript strict mode is mandatory (`strict: true`, `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`).
- Do not use `any` in production code. Use `unknown` + explicit narrowing.
- Model protocol as discriminated unions keyed by `type`/`method`; prefer exhaustive switches with `never` checks.
- Keep payload types shared and canonical in `src/protocol/types.ts`; do not duplicate event/command shapes elsewhere.
- ESM imports must be consistent with project config (`.js` suffix where required by Node16 module resolution).

## React + Ink Practices
- Functional components only. Keep render functions pure and deterministic.
- Side effects belong in hooks (`useEffect`) with explicit cleanup for timers, listeners, and child-process handlers.
- Use stable keys derived from protocol IDs (`turn_id`, `item_id`, `request_id`), never array index keys for dynamic lists.
- Keep derived UI data derived (memoized or computed), not duplicated in state.
- Keyboard handling is explicit and testable:
  - `InputArea` handles text entry and submit.
  - Approval keybindings live in `ApprovalModal`.
  - Global interrupt behavior is wired at the app/entry boundary.
- Preserve responsive terminal layout with Flexbox/Yoga primitives; avoid manual cursor math.

## Protocol and Error Handling
- Parse JSON only at transport boundary; malformed lines are ignored with minimal diagnostics to stderr.
- Unknown protocol events/commands must be ignored safely, never crash the UI loop.
- Outbound commands must be emitted as typed JSON-RPC lines only through protocol writers.
- Keep transport-agnostic contracts (`ProtocolReader`/`ProtocolWriter`) stable so stdio can be swapped for WebSocket later without UI rewrites.

## State Management Rules
- Keep turn state normalized and keyed by IDs; updates must be immutable.
- Streaming text handling must be deterministic (newline-gated buffer + explicit flush on turn completion).
- Approval queue behavior must be FIFO and request-id matched.
- Interrupt/cancellation paths must leave UI state consistent (clear active states, render interruption outcome once).

## Testing
- Place TUI tests under `tui/src/__tests__/` mirroring source modules.
- Prefer behavior assertions over snapshots for dynamic terminal output.
- Cover:
  - protocol reader/writer contract shape,
  - hook state transitions (`useTurns`, `useApprovalQueue`, `useLineBuffer`),
  - key interaction paths (`InputArea`, `ApprovalModal`, interrupt behavior),
  - deterministic rendering for tool panels and status bar.
- Tests must be deterministic and local-only (no live network, no real TTY dependency beyond ink-testing-library fakes).

## Validation Checks
- Validate inbound protocol events at the transport boundary before reducer/hook state updates.
- Treat unknown event types and malformed payloads as non-fatal: ignore safely and continue loop.
- Require exhaustive event/command handling in reducers/switches with an explicit `never`-style fallback.
- Require request/response identity checks (`request_id`, `turn_id`, `item_id`) before mutating queued or active state.
- For cross-language protocol edits, update Python event models and TypeScript protocol types in the same change.

## Quality Gates for TUI Changes
- `cd tui && npm run typecheck`
- `cd tui && npm run lint`
- `cd tui && npm test`
- For cross-boundary changes touching Python protocol/events, also run matching Python tests plus repo gates required by root `AGENTS.md`.

## Must-Pass Command Matrix
- Documentation-only changes in `tui/`:
  - No mandatory runtime gates.
  - If command examples or scripts are changed, run the directly affected command once and record result.
- Type-only or protocol-type changes (`src/protocol/types.ts`, shared TS types):
  - `cd tui && npm run typecheck`
  - `cd tui && npm run lint`
  - `cd tui && npm test -- --runInBand --findRelatedTests src/protocol/types.ts`
- Hook or reducer changes (`src/hooks/*`):
  - `cd tui && npm run typecheck`
  - `cd tui && npm run lint`
  - `cd tui && npm test -- --runInBand --findRelatedTests src/hooks`
- Component changes (`src/components/*`, `src/app.tsx`):
  - `cd tui && npm run typecheck`
  - `cd tui && npm run lint`
  - `cd tui && npm test -- --runInBand --findRelatedTests src/components src/app.tsx`
- Transport or entrypoint changes (`src/protocol/transports/*`, `src/index.ts`):
  - `cd tui && npm run typecheck`
  - `cd tui && npm run lint`
  - `cd tui && npm test`
  - Add or update at least one integration test that exercises the transport/entrypoint path.
- Cross-boundary protocol/event changes (Python + TUI):
  - `cd tui && npm run typecheck`
  - `cd tui && npm run lint`
  - `cd tui && npm test`
  - `pytest tests/core/test_tui_bridge.py -q`
  - Targeted Python protocol/event tests (`tests/protocol/`, `tests/core/test_event_adapter.py`, `tests/test_main.py`) matching touched contracts.

## Non-goals Guardrail
- Do not add web-only abstractions or browser dependencies in M4.
- Do not add feature polish that changes protocol contracts unless the milestone explicitly requires it.
