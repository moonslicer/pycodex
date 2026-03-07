# Milestone 9 TODO — /resume, /status, /new Slash Commands + Session Picker

## Goal
Add `/resume`, `/status`, and `/new` slash commands to pycodex TUI mode with an
interactive session picker and slash command autocomplete popup. Delivered in two
sequential PRs:
- PR 1: mechanical extraction of `session_store.py` + EventAdapter bug fix (no new UX).
- PR 2: atomic Python + TypeScript feature delivery (slash dispatch, protocol events, TUI components).

## Architecture
```
User types /res<Tab or Enter>
  -> SlashCommandPopup completes to "/resume "
  -> User presses Enter to submit
  -> TUI sends: {"method": "user.input", "params": {"text": "/resume"}}
  -> Bridge detects leading /, does NOT start agent turn
  -> Bridge filters current thread_id from results, calls list_sessions(config, limit=500)
  -> Bridge emits session.listed
  -> TUI opens SessionPickerModal
  -> User navigates list, presses Enter
  -> TUI sends: {"method": "session.resume", "params": {"thread_id": "..."}}
  -> Bridge guards against same-thread resume
  -> Bridge replays rollout, calls _activate_session(new_session)
  -> Bridge emits thread.started with new thread_id
  -> TUI reducer sees thread_id change, resets turns list
  -> User types next prompt into clean chat view
```

## Non-Goals
- Full upstream parity (30+ commands, cursor-based pagination, search, sorting, fork).
- `/fork` command.
- Feature flags.
- Server-sent session updates / live list refresh.

## Quality Gates
```
ruff check . --fix && ruff format .
mypy --strict pycodex/
pytest tests/ -v
cd tui && npm run typecheck
cd tui && npm run lint
cd tui && npm test
```

---

## TODO Tasks

### PR 1 — Extraction and Bug Fix

- [ ] T1: Extract `session_store.py` module (`pycodex/core/session_store.py`, `pycodex/__main__.py`)
  - Move out of `__main__.py` without logic changes: `_resolve_resume_rollout_path` -> `resolve_resume_rollout_path`, `_read_session_closed` -> `read_session_closed`, `_list_sessions` -> `list_sessions`, `_last_user_message_from_history` -> `last_user_message_from_history`, `_rollout_date_token` -> `rollout_date_token`.
  - Add `SessionSummaryRecord` dataclass (`thread_id`, `status`, `turn_count`, `token_total`, `last_user_message`, `date`).
  - `list_sessions` is uncapped (`limit: int | None = None`); CLI callers pass `limit=None`; bridge caller passes `limit=500` at its call site.
  - `__main__.py` keeps thin wrappers calling into `session_store` — no behavior change for CLI session subcommands.
  - Add `session_store` ownership entry to `docs/ai/system-map.md`.
  - Verify:
    - `.venv/bin/pytest tests/test_main.py -k "session" -q`

- [ ] T2: Fix `EventAdapter` thread ID in `TuiBridge.__post_init__` (`pycodex/core/tui_bridge.py`)
  - Change `_adapter` from `field(default_factory=EventAdapter, init=False)` to `field(init=False)` with no factory.
  - Initialize in `__post_init__`: `self._adapter = EventAdapter(thread_id=self.session.thread_id)`.
  - Ensures `thread.started` carries the resumed session's `thread_id`, not a random UUID.
  - Verify:
    - `.venv/bin/pytest tests/core/test_tui_bridge.py -k "thread_id" -q`

- [ ] T3: Tests for PR 1 (`tests/core/test_session_store.py`, `tests/core/test_tui_bridge.py`, `tests/test_main.py`, `tests/core/test_session.py`)
  - `test_session_store.py` (new): `list_sessions` uncapped / capped / newest-first / closed fast-path / incomplete fallback; `read_session_closed` valid / empty / truncated / non-closed; `resolve_resume_rollout_path` by thread ID / explicit path / not-found raises.
  - `test_tui_bridge.py` additions: `thread.started` on init carries `session.thread_id`; resumed session bridge emits `thread.started` with replayed `thread_id`.
  - `tests/test_main.py` regression: `session list`, `session read`, `session archive`, `session unarchive` still work after extraction.
  - `tests/core/test_session.py` additions: `close_rollout()` with no turns taken creates no file and leaves `_rollout_closed` False (ghost file prevention).
  - Verify (PR 1 gates):
    - `.venv/bin/ruff check . --fix && .venv/bin/ruff format .`
    - `.venv/bin/mypy --strict pycodex/`
    - `.venv/bin/pytest tests/ -v`

---

### PR 2 — Slash Commands + Session Picker (Atomic Python + TUI)

- [ ] T4: New Python protocol events (`pycodex/protocol/events.py`)
  - Add six `_FrozenModel` classes: `SessionSummary`, `SessionListed` (`session.listed`), `SessionStatus` (`session.status`), `SlashUnknown` (`slash.unknown`), `SlashBlocked` (`slash.blocked`), `SessionError` (`session.error`).
  - Extend `ProtocolEvent` union with all six.
  - Verify:
    - `.venv/bin/mypy --strict pycodex/`

- [ ] T5: Slash dispatch and handlers (`pycodex/core/tui_bridge.py`)
  - In `_handle_user_input`: detect leading `/`, dispatch to `_handle_slash_command`, return early (skip agent turn).
  - `_handle_slash_command`: match `resume` / `status` / `new` / default (`SlashUnknown`).
  - `_slash_status`: always allowed; emit `SessionStatus` with current thread_id, turn count, token usage.
  - `_slash_resume`: blocked during active turn (`SlashBlocked`); call `list_sessions(config, limit=500)`, filter out current `thread_id`, emit `SessionListed`; wrap in try/except -> `SessionError(operation="list")`.
  - `_slash_new`: blocked during active turn (`SlashBlocked`); create fresh `Session`, configure rollout, call `_activate_session`; wrap in try/except -> `SessionError(operation="new")`.
  - Verify:
    - `.venv/bin/pytest tests/core/test_tui_bridge.py -k "slash" -q`

- [ ] T6: `_activate_session` and JSON-RPC handlers (`pycodex/core/tui_bridge.py`)
  - `_activate_session(new_session)`: close current rollout, clear `_pending_approvals`, swap `self.session`, create fresh `EventAdapter(thread_id=new_session.thread_id)`, emit `thread.started`.
  - `_handle_session_resume(params)`: active-turn guard -> `SessionError`; validate `thread_id` param; same-thread guard; resolve rollout path; replay; restore session; configure recorder; call `_activate_session`. Entire body in try/except -> `SessionError(operation="resume")`.
  - `_handle_session_new()`: active-turn guard -> `SessionError`; create session; configure rollout; call `_activate_session`. Wrap in try/except -> `SessionError(operation="new")`.
  - Wire both into `_handle_line` dispatch.
  - Verify:
    - `.venv/bin/pytest tests/core/test_tui_bridge.py -k "session_resume or session_new or activate" -q`

- [ ] T7: TypeScript protocol types (`tui/src/protocol/types.ts`)
  - Add event types: `SessionSummaryItem`, `SessionListedEvent`, `SessionStatusEvent`, `SlashUnknownEvent`, `SlashBlockedEvent`, `SessionErrorEvent`.
  - Add command types: `SessionResumeCommand`, `SessionNewCommand`.
  - Extend `ProtocolEvent` union with all six event types.
  - Extend `Command` union with both command types.
  - Verify:
    - `cd tui && npm run typecheck`

- [ ] T8: TypeScript transport + writer (`tui/src/protocol/transports/stdio.ts`, `tui/src/protocol/writer.ts`)
  - `stdio.ts` — add cases to `isProtocolEvent` for all six new event types (outer-shape validation only for `session.listed`).
  - `StdioWriter` — add `sendSessionResume(threadId: string): void` and `sendSessionNew(): void`.
  - `writer.ts` — add both methods to `ProtocolWriter` interface.
  - Update `MockWriter` in `tui/src/__tests__/index.test.ts` with no-op stubs for both methods.
  - Verify:
    - `cd tui && npm run typecheck && npm run lint`

- [ ] T9: `useTurns` thread reset fix (`tui/src/hooks/useTurns.ts`)
  - `thread.started` reducer: if `state.threadId !== null && state.threadId !== event.thread_id`, return `{ threadId: event.thread_id, turns: [] }`.
  - Otherwise return `{ ...state, threadId: event.thread_id }` (startup and same-id reconnect unchanged).
  - Verify:
    - `cd tui && npm test -- --testPathPattern useTurns`

- [ ] T10: `useSystemNotices` hook (`tui/src/hooks/useSystemNotices.ts`, new)
  - Export `SystemNotice = { id: string; text: string }`.
  - `useSystemNotices(events)`: convert `session.status`, `slash.unknown`, `slash.blocked`, `session.error` events to formatted notice strings; ignore all other types; notices accumulate, cleared on full event reset.
  - Verify:
    - `cd tui && npm test -- --testPathPattern useSystemNotices`

- [ ] T11: `useSlashCompletion` hook (`tui/src/hooks/useSlashCompletion.ts`, new)
  - Export `SLASH_COMMANDS` catalog with `resume`, `status`, `new` entries.
  - `isOpen`: true when `value.startsWith("/") && !value.includes(" ")`.
  - `matches`: filter by prefix on typed portion.
  - `selectedIndex`: clamped, reset to 0 on filter change.
  - `complete()`: returns `"/${matches[selectedIndex].command} "` or `null` if empty.
  - `dismiss()`: forces `isOpen` false until `value` changes.
  - Verify:
    - `cd tui && npm test -- --testPathPattern useSlashCompletion`

- [ ] T12: `SlashCommandPopup` component (`tui/src/components/SlashCommandPopup.tsx`, new)
  - Props: `matches: readonly SlashCommandDef[]`, `selectedIndex: number`.
  - Renders one row per match; selected row highlighted (inverse); `/<command>  <description>` format.
  - Returns `null` when `matches` is empty. No keyboard handling.
  - Verify:
    - `cd tui && npm run typecheck`

- [ ] T13: `InputArea` autocomplete integration (`tui/src/components/InputArea.tsx`)
  - Import `useSlashCompletion` and `SlashCommandPopup`.
  - Call `useSlashCompletion(editorState.value)` inside component.
  - Add popup key intercept in `useInput` before `computeKeyEvent`: `↑`/`↓` move selection (suspend history recall while open); `Enter`/`Tab` complete (Tab falls through if no match); `Esc` dismisses; other keys fall through.
  - Render `SlashCommandPopup` above prompt line when `isOpen && matches.length > 0`.
  - `computeKeyEvent` is unchanged.
  - Verify:
    - `cd tui && npm run typecheck && npm test -- --testPathPattern inputArea`

- [ ] T14: `SessionPickerModal` component (`tui/src/components/SessionPickerModal.tsx`, new)
  - Props: `sessions: SessionSummaryItem[]`, `onSelect: (threadId: string) => void`, `onDismiss: () => void`.
  - Bordered box with title, session rows (date / truncated thread_id / turns / tokens / status / truncated last message), selected row highlighted, footer `[Enter] resume  [Esc] cancel`.
  - Keys: `↑`/`k` up, `↓`/`j` down, `Enter` -> `onSelect`, `Esc` -> `onDismiss`.
  - No search or pagination in v1. Empty list renders gracefully.
  - Verify:
    - `cd tui && npm run typecheck`

- [ ] T15: `app.tsx` wiring (`tui/src/app.tsx`)
  - On `session.listed`: normalize rows via `toSessionSummaryItems(payload)` (drops malformed rows), open `SessionPickerModal` with valid rows.
  - On `session.status` / `slash.*` / `session.error`: feed to `useSystemNotices`.
  - `SessionPickerModal.onSelect(threadId)` -> `writer.sendSessionResume(threadId)`, close modal.
  - `SessionPickerModal.onDismiss()` -> close modal (no command sent).
  - Disable `InputArea` while picker modal is open.
  - Render `SystemNotice[]` as dimmed lines above input area.
  - Verify:
    - `cd tui && npm run typecheck`

- [ ] T16: Python tests for PR 2 (`tests/core/test_tui_bridge.py`)
  - `/status` emits `session.status` with correct counts; also allowed during mocked active turn.
  - `/resume` emits `session.listed` excluding current `thread_id`; emits `slash.blocked` during active turn; returns empty list when no sessions.
  - `/new` swaps session, emits `thread.started` with different `thread_id`; emits `slash.blocked` during active turn.
  - `session.resume` with valid ID: replays, swaps, emits `thread.started`.
  - `session.resume` guards: same-thread -> `session.error`; missing param -> `session.error`; unknown ID -> `session.error`; active turn -> `session.error`; `_activate_session` raises -> `session.error` (no crash).
  - `session.new` when `_activate_session` raises -> `session.error` (no crash).
  - After `_activate_session`, `_pending_approvals` is cleared.
  - Unknown slash command -> `slash.unknown`.
  - `list_sessions` raising during `/resume` -> `session.error` (no crash).
  - Verify:
    - `.venv/bin/pytest tests/core/test_tui_bridge.py -v`

- [ ] T17: TypeScript tests for PR 2
  - `reader.test.ts`: parse all six new event shapes; `session.listed` with empty array valid; non-array sessions rejected; mixed valid/invalid rows passes transport boundary.
  - `app.test.tsx`: `toSessionSummaryItems` keeps valid rows and drops malformed; all-malformed rows opens picker with empty state (no crash).
  - `writer.test.ts`: `sendSessionResume("abc")` and `sendSessionNew()` write correct JSON-RPC lines.
  - `useTurns.test.ts`: same-id `thread.started` no reset; different-id reset to `[]`; null-start no reset.
  - `useSlashCompletion.test.ts` (new): full spec from §2.17 (empty input, `/` alone, prefix filter, dismiss, complete, clamp, etc.).
  - `useSystemNotices.test.ts` (new): all four event types produce notices; other types ignored; multiple accumulate.
  - `inputArea.test.ts`: open on `/`, filter on `/r`, arrow keys intercept, Tab/Enter complete, Esc dismiss, Tab no-match falls through, history recall regression.
  - `sessionPickerModal.test.tsx` (new): renders rows, arrow down moves selection, Enter calls `onSelect`, Esc calls `onDismiss`, empty list graceful.
  - Verify:
    - `cd tui && npm test`

- [ ] T18: Final quality gates (PR 2 lock-in)
  - Verify:
    - `.venv/bin/ruff check . --fix && .venv/bin/ruff format .`
    - `.venv/bin/mypy --strict pycodex/`
    - `.venv/bin/pytest tests/ -v`
    - `cd tui && npm run typecheck`
    - `cd tui && npm run lint`
    - `cd tui && npm test`

---

## Task Dependency Graph
```
T1 (session_store extract) ──> T3 (PR 1 tests)
T2 (EventAdapter fix)      ──> T3

T3 (PR 1 complete) ──> T4 (protocol events) ──> T5 (slash handlers) ──> T6 (activate + RPC handlers)
                    ──> T7 (TS types)        ──> T8 (transport + writer)
                    ──> T9 (useTurns fix)
                    ──> T10 (useSystemNotices)
                    ──> T11 (useSlashCompletion) ──> T12 (SlashCommandPopup) ──> T13 (InputArea)
                    ──> T14 (SessionPickerModal)

T6 + T8 + T9 + T10 + T13 + T14 ──> T15 (app.tsx wiring)
T5 + T6                         ──> T16 (Python tests)
T7 + T8 + T9 + T11 + T13 + T14 ──> T17 (TS tests)
T15 + T16 + T17                 ──> T18 (final gates)
```

## Acceptance Criteria
1. `pycodex --tui-mode` fresh session: type `/status` -> `session.status` with correct thread_id and zero counts.
2. After one turn: `/status` shows non-zero turn_count and token counts.
3. Typing `/` opens autocomplete popup showing all three commands with descriptions.
4. Typing `/r` filters popup to only `resume`; Tab or Enter completes to `/resume `.
5. Up/Down navigate popup; Esc dismisses without completing.
6. Tab with no matches (e.g. `/xyz`) does not autocomplete; input unchanged.
7. Up/Down still navigate history when popup is closed (regression).
8. `/resume` with no prior sessions -> `session.listed` empty array; picker shows empty state gracefully.
9. `/resume` with prior sessions -> picker opens; current session absent; selecting another loads its history.
10. First prompt after resume continues the replayed conversation.
11. `/new` -> new `thread.started` with different thread_id; turns list clears.
12. `session.resume` with active thread_id via JSON-RPC -> `session.error`, no mutation.
13. Slash commands / `session.resume` via JSON-RPC during mocked active turn -> `session.error` or `slash.blocked`.
14. Any handler exception -> `session.error` emitted; bridge loop continues.
15. `session.resume` with unknown thread_id -> `session.error` notice shown, no crash.
16. `--tui-mode --resume <id>`: `thread.started` carries resumed session's `thread_id` (not random UUID). [PR 1 bug fix]

## Completion Checklist
- [ ] T1 complete
- [ ] T2 complete
- [ ] T3 complete
- [ ] T4 complete
- [ ] T5 complete
- [ ] T6 complete
- [ ] T7 complete
- [ ] T8 complete
- [ ] T9 complete
- [ ] T10 complete
- [ ] T11 complete
- [ ] T12 complete
- [ ] T13 complete
- [ ] T14 complete
- [ ] T15 complete
- [ ] T16 complete
- [ ] T17 complete
- [ ] T18 complete
- [ ] All quality gates pass
- [ ] Manual acceptance criteria verified
