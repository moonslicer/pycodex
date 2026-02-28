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

## Quality Gates for TUI Changes
- `cd tui && npm run typecheck`
- `cd tui && npm run lint`
- `cd tui && npm test`
- For cross-boundary changes touching Python protocol/events, also run matching Python tests plus repo gates required by root `AGENTS.md`.

## Non-goals Guardrail
- Do not add web-only abstractions or browser dependencies in M4.
- Do not add feature polish that changes protocol contracts unless the milestone explicitly requires it.
