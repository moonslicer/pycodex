# Compaction & Context Status Improvements Plan

## Current State

The compaction pipeline is fully functional end-to-end. The Python backend emits `context.compacted`
JSONL events with all relevant data; the TypeScript TUI tracks compaction state per turn and shows
it in the status bar and in debug mode (`showToolCallSummary`). However, several gaps remain vs.
the Claude Code TUI experience.

### What already works

| Component | Status |
|---|---|
| `CompactionOrchestrator` detects threshold + summarizes | Done |
| `ContextCompacted` agent event emitted after compaction | Done |
| `context.compacted` protocol event with full metadata | Done |
| `TurnState.compaction` tracked per-turn in `useTurns.ts` | Done |
| StatusBar shows `compaction: triggered (replaced N; context X% / threshold Y%)` | Done |
| `summarizeCompactionDebugLinesForTurn` in ChatView (debug mode only) | Done |

### What is missing

| Gap | Impact |
|---|---|
| No context fill % in status bar (no `context_window_tokens` in `SessionStatus`) | No token meter |
| Compaction notice is debug-only / status-bar-only, not inline in conversation | Low visibility |
| Hydrated turns on resume carry no compaction metadata | Resume UX blind to compaction |
| No proactive "context pressure" warning before compaction fires | No early warning |
| `SessionStatus` has no `compaction_count` | `/status` incomplete |

---

## Improvements

### 1. Token fill meter in status bar

**Goal:** Status bar shows `context: [████░░] 78%` (or equivalent text bar) so users always see
how full the context window is, not just raw token counts.

**Root cause:** `SessionStatus` protocol event lacks `context_window_tokens`, so the TUI cannot
compute a fill ratio. Additionally, the fill is only available on `/status` demand, not live after
each turn.

**Python changes (`pycodex/`):**

- `pycodex/protocol/events.py` — add `context_window_tokens: StrictInt` to `SessionStatus`
- `pycodex/core/tui_bridge.py` — populate it in `_slash_status()` from
  `self.session.config.compaction_context_window_tokens` (fallback to 0 if config is None)
- `tests/core/test_session.py` or status-related tests — update fixtures

**TypeScript changes (`tui/`):**

- `tui/src/protocol/types.ts` — add `context_window_tokens: number` to `SessionStatusEvent`
- `tui/src/components/StatusBar.tsx` — replace raw `usage latest(in/out): X/Y` with a fill bar:
  `context: [████░░] 78% (128k)` when `context_window_tokens > 0`, using `input_tokens /
  context_window_tokens` for the ratio. Keep raw counts as fallback.
- `tui/src/__tests__/statusBar.test.ts` — add fill bar format tests

**Effort:** Small — ~4 files, ~40 lines total.

---

### 2. Inline compaction notice in conversation

**Goal:** When compaction fires during a turn, show a visible notice inline in the conversation
(not just in the status bar or debug mode), similar to Claude Code's
`Context compacted (24 messages summarized, 78% -> 20%)`.

**Root cause:** `ChatView.tsx` renders `summarizeCompactionDebugLinesForTurn` only when
`showToolCallSummary=true` (debug mode). Non-debug users never see the inline notice.

**Python changes:** None — `context.compacted` event already carries all needed data.

**TypeScript changes (`tui/`):**

- `tui/src/components/ChatView.tsx` — render a compaction notice row unconditionally (not
  gated on `showToolCallSummary`) when `turn.compaction.status === "triggered"`. Style it
  distinctly from debug lines (e.g., `color="cyan"` or `dimColor` with a marker prefix like
  `~ Context compacted: 24 messages summarized (78% -> 20% context used)`).
- `tui/src/__tests__/chatView.test.ts` — add test for compaction notice rendering

**Effort:** Small — ~2 files, ~20 lines.

---

### 3. Add `compaction_count` to `/status`

**Goal:** `/status` reports how many times compaction has fired in the current session, giving
users an easy way to check session health.

**Root cause:** `Session` doesn't track a compaction counter. `SessionStatus` has no
`compaction_count` field.

**Python changes (`pycodex/`):**

- `pycodex/core/session.py` — add `_compaction_count: int` field; increment it in
  `replace_range_with_system_summary()`; expose via `compaction_count()` method
- `pycodex/protocol/events.py` — add `compaction_count: StrictInt` to `SessionStatus`
- `pycodex/core/tui_bridge.py` — populate `compaction_count` in `_slash_status()`
- `tests/core/test_session.py` — test counter increments

**TypeScript changes (`tui/`):**

- `tui/src/protocol/types.ts` — add `compaction_count: number` to `SessionStatusEvent`
- `tui/src/components/StatusBar.tsx` — include in status display when nonzero:
  `compacted: 2x`

**Effort:** Small — ~5 files, ~30 lines.

---

### 4. Surface compaction in hydrated (resumed) turns

**Goal:** When a session is resumed, turns that were compacted are flagged in the TUI so the user
knows historical context was summarized. Optionally show the summary text.

**Root cause:** `_build_hydrated_turns()` in `tui_bridge.py` only processes `user`/`assistant`
items; it skips system items (compaction summary blocks). `toHydratedTurnState()` in `useTurns.ts`
always sets `compaction: { status: "idle", detail: null }`.

**Python changes (`pycodex/`):**

- `pycodex/protocol/events.py` — add optional `compaction_summary: str | None` field to
  `HydratedTurn` (the text from the summary block immediately preceding compacted turns)
- `pycodex/core/tui_bridge.py` — update `_build_hydrated_turns()` to detect system items with
  `_SUMMARY_BLOCK_MARKER` content and attach the summary text to the preceding or following
  `HydratedTurn` boundary
- `tests/core/test_session.py` — test hydrated turns with compaction summary

**TypeScript changes (`tui/`):**

- `tui/src/protocol/types.ts` — add `compaction_summary?: string | null` to `HydratedTurnItem`
- `tui/src/hooks/useTurns.ts` — `toHydratedTurnState()` sets `compaction.status = "triggered"`
  and stores summary text if `compaction_summary` is present
- `tui/src/components/ChatView.tsx` — render a muted notice for hydrated compacted turns:
  `~ [Resumed: prior context was compacted]`
- Tests updated accordingly

**Effort:** Medium — ~6 files, ~60 lines. The boundary logic in `_build_hydrated_turns()` requires
care to correctly associate summary blocks with the right turn boundary.

---

### 5. Context pressure warning (proactive)

**Goal:** Emit a warning event when the context window is getting full but compaction has not yet
fired (e.g., remaining ratio between threshold and threshold * 1.5), giving users a heads-up before
the turn that triggers compaction.

**Root cause:** The agent only reports compaction after it fires. There is no pre-emptive signal.

**Python changes (`pycodex/`):**

- `pycodex/protocol/events.py` — add new `ContextPressure` event:
  ```
  type: "context.pressure"
  thread_id: str
  turn_id: str
  remaining_ratio: float
  context_window_tokens: int
  estimated_prompt_tokens: int
  ```
- `pycodex/core/agent.py` — in `_compact_history_if_needed()` (or just before the model sample),
  check if remaining ratio is below `threshold * 1.5` but above `threshold`; if so emit
  `ContextPressure` agent event
- `pycodex/core/agent.py` — add `ContextPressure` to `AgentEvent` union
- `pycodex/core/event_adapter.py` — map `ContextPressure` agent event to `context.pressure`
  protocol event
- Tests for new event flow

**TypeScript changes (`tui/`):**

- `tui/src/protocol/types.ts` — add `ContextPressureEvent` type; add to `ProtocolEvent` union
- `tui/src/hooks/useTurns.ts` — track `pressureWarning: boolean` on `TurnState`; set on
  `context.pressure` event
- `tui/src/components/StatusBar.tsx` — when pressure is active, highlight fill bar in yellow
- `tui/src/__tests__/` — tests for new event handling

**Effort:** Medium — ~7 files, ~80 lines. Straightforward to add but touches the agent event union
and adapter which require corresponding test updates.

---

## Summary

| # | Improvement | Layer | Effort | Priority |
|---|---|---|---|---|
| 1 | Token fill meter in status bar | Python + TS | Small | High |
| 2 | Inline compaction notice in conversation | TS only | Small | High |
| 3 | `compaction_count` in `/status` | Python + TS | Small | Medium |
| 4 | Compaction metadata in hydrated turns | Python + TS | Medium | Medium |
| 5 | Context pressure warning event | Python + TS | Medium | Low |

Items 1 and 2 are independent of each other and have no shared dependencies — they can be built in
parallel. Items 3-5 each build on clean protocol extension patterns already established in the
codebase and are self-contained.
