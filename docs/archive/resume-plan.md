# Resume / Slash Command Implementation Plan

## Goal

Add `/resume`, `/status`, and `/new` slash commands to pycodex TUI mode with an
interactive session picker and slash command autocomplete popup. Delivered in two
sequential PRs.

---

## Background and Prior Analysis

The upstream Codex (Rust) TUI has ~30 slash commands including `/resume`, which opens
a paginated, searchable session picker backed by cursor-based pagination and a SQLite
session index. We are not attempting full parity. The goal is a correct, minimal
implementation that fits pycodex's architecture and can be extended later.

Two design proposals were evaluated. Key conclusions:

- `session_store.py` extraction is required (circular import: `__main__` imports
  `TuiBridge`; `tui_bridge` cannot import from `__main__`).
- Python and TUI protocol changes must ship atomically (unknown events are gracefully
  dropped, not crashed, but the UX is broken if one side ships without the other).
- Feature flag is overkill: the slash intercept is purely additive and degrades
  gracefully on old TUI builds.
- Phased delivery contradicts atomic delivery. Ship the feature as one PR after the
  extraction PR.
- A pre-existing bug exists independent of this work: `TuiBridge.__post_init__`
  initializes `EventAdapter` with its own random UUID instead of `session.thread_id`,
  so `--tui-mode --resume <id>` emits a `thread.started` with the wrong thread ID. Fix
  this in PR 1.

### Design review findings addressed in this plan

Five issues were identified during design review and are explicitly addressed below:

| Finding | Where addressed |
|---|---|
| Cap in shared `list_sessions` changes CLI behavior | §1.1: cap moved to bridge call site; shared fn is uncapped |
| Unguarded slash handlers can crash bridge loop | §2.5, §2.6: all handlers wrapped in try/except; emit `session.error` on any failure |
| Same-thread resume causes silent turn dedup collision | §2.6: bridge filters current thread from listing; handler guards same-thread request |
| `MockWriter` in `index.test.ts` missing from file list | §2.19: file added |
| Active-turn slash UX unreachable through disabled `InputArea` | §2.4: clarified as bridge-level contract; acceptance criteria scoped to JSON-RPC tests |

---

## Non-Goals

- Full upstream parity (30+ commands, cursor-based pagination, search, sorting, fork).
- `/fork` command.
- Feature flags.
- Server-sent session updates / live list refresh.

---

## PR 1: Extraction and Bug Fix

**Purpose:** Mechanical refactor plus one bug fix. No new user-visible behavior.
Independently verifiable: all existing tests pass unchanged.

### 1.1 New module: `pycodex/core/session_store.py`

Move the following out of `__main__.py` into this module with no logic changes:

| Function | Current location |
|---|---|
| `_resolve_resume_rollout_path` | `__main__.py:412` — becomes `resolve_resume_rollout_path(config, resume) -> Path` (async) |
| `_read_session_closed` | `__main__.py:644` — becomes `read_session_closed(path) -> SessionClosed \| None` |
| `_list_sessions` | derived from `_session_list` — becomes `list_sessions(config, *, limit: int \| None = None) -> list[SessionSummaryRecord]` |
| `_last_user_message_from_history` | `__main__.py:804` — becomes `last_user_message_from_history(history) -> str \| None` |
| `_rollout_date_token` | `__main__.py:816` — becomes `rollout_date_token(filename) -> str` |

`SessionSummaryRecord` is a plain dataclass (not a protocol model — that lives in
`events.py`):

```python
@dataclass(frozen=True, slots=True)
class SessionSummaryRecord:
    thread_id: str
    status: Literal["closed", "incomplete"]
    turn_count: int
    token_total: int          # input + output combined
    last_user_message: str | None
    date: str                 # "YYYYMMDD" token from rollout filename
```

**`list_sessions` is uncapped.** The `limit` parameter defaults to `None` (no cap).
The CLI session subcommands pass `limit=None` — their behavior is unchanged. The
bridge's `/resume` slash handler passes `limit=500` at the call site to bound the
`session.listed` payload. The cap is a bridge UX concern, not a storage concern; it
does not belong in the shared function.

`__main__.py` keeps thin wrappers that call into `session_store` for the CLI session
subcommands. No behavior change.

### 1.2 Bug fix: `EventAdapter` thread ID in `TuiBridge`

**Problem:** `TuiBridge.__post_init__` creates `EventAdapter()` with a random UUID.
When the session is a resumed session with an existing `thread_id`, the emitted
`thread.started` carries the wrong ID. The TUI sees a thread identity that does not
match the rollout.

**Fix:** In `tui_bridge.py`:

```python
def __post_init__(self) -> None:
    self._adapter = EventAdapter(thread_id=self.session.thread_id)
    self._emit_protocol_event(self._adapter.start_thread())
```

The `_adapter` field changes from `field(default_factory=EventAdapter, init=False)` to
`field(init=False)` with no factory (initialized in `__post_init__`).

### 1.3 Tests for PR 1

**`tests/core/test_session_store.py`** (new):
- `list_sessions` with `limit=None` returns all sessions (no cap).
- `list_sessions` with `limit=N` returns at most N sessions.
- `list_sessions` returns closed sessions using fast-path (spy confirms `replay_rollout`
  not called for closed sessions).
- `list_sessions` falls back to replay for incomplete sessions.
- `list_sessions` returns records newest-first.
- `read_session_closed` returns `SessionClosed` when last line is valid.
- `read_session_closed` returns `None` on empty file, truncated file, non-closed type.
- `resolve_resume_rollout_path` resolves by thread ID.
- `resolve_resume_rollout_path` resolves explicit path.
- `resolve_resume_rollout_path` raises `RolloutReplayError` when not found.

**`tests/core/test_tui_bridge.py`** — add:
- `thread.started` emitted on init carries `session.thread_id` (not a random UUID).
- Resumed session bridge emits `thread.started` with the replayed `thread_id`.

**`tests/test_main.py`** — regression:
- `session list`, `session read`, `session archive`, `session unarchive` still work
  after the extraction refactor.

### 1.4 Files changed in PR 1

```
pycodex/core/session_store.py      (new)
pycodex/core/tui_bridge.py         (EventAdapter init fix)
pycodex/__main__.py                (import from session_store, thin wrappers)
tests/core/test_session_store.py   (new)
tests/core/test_tui_bridge.py      (two new tests)
tests/test_main.py                 (regression coverage)
docs/ai/system-map.md              (add session_store ownership entry)
```

### 1.5 Quality gates for PR 1

```
ruff check . --fix && ruff format .
mypy --strict pycodex/
pytest tests/ -v
```

---

## PR 2: Slash Commands + Session Picker (Atomic Python + TUI)

**Purpose:** Full feature delivery. Python and TUI changes in one PR. Neither side is
useful without the other.

---

### 2.1 Architecture overview

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

---

### 2.2 New protocol events (Python: `pycodex/protocol/events.py`)

```python
class SessionSummary(_FrozenModel):
    thread_id: str
    status: Literal["closed", "incomplete"]
    turn_count: int
    token_total: int
    last_user_message: str | None
    date: str  # "YYYYMMDD"

class SessionListed(_FrozenModel):
    type: Literal["session.listed"] = "session.listed"
    sessions: list[SessionSummary]

class SessionStatus(_FrozenModel):
    type: Literal["session.status"] = "session.status"
    thread_id: str
    turn_count: int
    input_tokens: int
    output_tokens: int

class SlashUnknown(_FrozenModel):
    type: Literal["slash.unknown"] = "slash.unknown"
    command: str

class SlashBlocked(_FrozenModel):
    type: Literal["slash.blocked"] = "slash.blocked"
    command: str
    reason: Literal["active_turn"]

class SessionError(_FrozenModel):
    type: Literal["session.error"] = "session.error"
    operation: Literal["resume", "new", "list"]
    message: str
```

Extend `ProtocolEvent` union with all six.

---

### 2.3 New JSON-RPC commands accepted by bridge

Extend `_handle_line` in `tui_bridge.py`:

| Method | Params | Effect |
|---|---|---|
| `session.resume` | `{ thread_id: string }` | replay rollout + swap active session |
| `session.new` | `{}` | create fresh session + swap |

All error conditions — malformed params, same-thread resume, replay failure, activation
failure — emit `session.error`. No exceptions propagate out of handlers.

---

### 2.4 Slash dispatch in `tui_bridge.py`

In `_handle_user_input`:

```python
async def _handle_user_input(self, text: str) -> None:
    if text.startswith("/"):
        await self._handle_slash_command(text[1:].strip())
        return
    # existing active-turn guard + task creation unchanged
```

```python
async def _handle_slash_command(self, text: str) -> None:
    parts = text.split(None, 1)
    command = parts[0].lower() if parts else ""
    match command:
        case "resume":
            await self._slash_resume()
        case "status":
            self._slash_status()
        case "new":
            await self._slash_new()
        case _:
            self._emit_protocol_event(SlashUnknown(command=command))
```

**Availability policy:**

| Command | During active turn |
|---|---|
| `/status` | allowed |
| `/new` | blocked → emit `SlashBlocked` |
| `/resume` | blocked → emit `SlashBlocked` |
| unknown | always emit `SlashUnknown` |

**Active-turn policy is a bridge-level contract, not a TUI UX guarantee.** The current
`InputArea` is fully disabled while a turn is active, so a user cannot type slash
commands during a turn through the TUI. The availability rules exist for programmatic
API use and are validated in Python tests via direct JSON-RPC messages. The TUI
acceptance criteria for active-turn behavior are scoped accordingly.

---

### 2.5 Slash handlers

All slash handlers are wrapped in try/except. Any unhandled exception emits
`session.error` and returns — it does not propagate to the bridge read loop.

**`/status`** — synchronous, always allowed, no failure modes:
```python
def _slash_status(self) -> None:
    usage = self.session.cumulative_usage()
    self._emit_protocol_event(SessionStatus(
        thread_id=self.session.thread_id,
        turn_count=self.session.completed_turn_count(),
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
    ))
```

**`/resume`** — blocked during active turn, otherwise lists sessions. Cap of 500
applied here at the call site, not in `list_sessions` itself. Current session filtered
out so it does not appear in the picker:

```python
async def _slash_resume(self) -> None:
    if self._active_turn is not None and not self._active_turn.done():
        self._emit_protocol_event(SlashBlocked(command="resume", reason="active_turn"))
        return
    try:
        current_thread_id = self.session.thread_id
        records = await list_sessions(self.session.config, limit=500)
        sessions = [
            SessionSummary(
                thread_id=r.thread_id,
                status=r.status,
                turn_count=r.turn_count,
                token_total=r.token_total,
                last_user_message=r.last_user_message,
                date=r.date,
            )
            for r in records
            if r.thread_id != current_thread_id
        ]
        self._emit_protocol_event(SessionListed(sessions=sessions))
    except Exception as exc:
        self._emit_protocol_event(SessionError(operation="list", message=str(exc)))
```

**`/new`** — blocked during active turn, otherwise activates a fresh session:

```python
async def _slash_new(self) -> None:
    if self._active_turn is not None and not self._active_turn.done():
        self._emit_protocol_event(SlashBlocked(command="new", reason="active_turn"))
        return
    try:
        config = self.session.config
        new_session = Session(config=config)
        _configure_rollout_persistence(new_session, config=config)
        await self._activate_session(new_session)
    except Exception as exc:
        self._emit_protocol_event(SessionError(operation="new", message=str(exc)))
```

---

### 2.6 `_activate_session` and session switching

**`_activate_session`** — single code path for all session switches. Callers are
responsible for ensuring no active turn is running before calling this.

```python
async def _activate_session(self, new_session: Session) -> None:
    """Close current session, swap to new_session, emit thread.started."""
    await self.session.close_rollout()
    self._pending_approvals.clear()
    self.session = new_session
    self._adapter = EventAdapter(thread_id=new_session.thread_id)
    self._emit_protocol_event(self._adapter.start_thread())
```

Rules:
- Never called while active turn is running (callers guard).
- Always closes current rollout before swap.
- Always clears pending approval queue (approvals belong to the old session).
- Always creates a fresh `EventAdapter` with the new session's `thread_id`.
- Emits exactly one `thread.started` per activation.

**`session.resume` JSON-RPC handler** — same-thread guard is the first domain check
after the active-turn guard. The entire handler body is wrapped so any failure — param
validation, rollout resolution, replay, or activation — emits `session.error` and
returns cleanly without propagating to the bridge loop:

```python
async def _handle_session_resume(self, params: dict[str, Any]) -> None:
    if self._active_turn is not None and not self._active_turn.done():
        self._emit_protocol_event(SessionError(
            operation="resume", message="Cannot resume during active turn."
        ))
        return
    try:
        thread_id = params.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            self._emit_protocol_event(SessionError(
                operation="resume", message="Missing or invalid thread_id parameter."
            ))
            return
        if thread_id == self.session.thread_id:
            self._emit_protocol_event(SessionError(
                operation="resume", message="Requested session is already active."
            ))
            return
        rollout_path = await resolve_resume_rollout_path(
            config=self.session.config, resume=thread_id
        )
        replay_state = replay_rollout(rollout_path)
        new_session = Session(config=self.session.config, thread_id=replay_state.thread_id)
        new_session.restore_from_rollout(
            history=replay_state.history,
            cumulative_usage=replay_state.cumulative_usage,
            turn_count=replay_state.turn_count,
        )
        new_session.configure_rollout_recorder(
            recorder=RolloutRecorder(path=rollout_path),
            path=rollout_path,
        )
        await self._activate_session(new_session)
    except Exception as exc:
        self._emit_protocol_event(SessionError(operation="resume", message=str(exc)))
```

**`session.new` JSON-RPC handler:**

```python
async def _handle_session_new(self) -> None:
    if self._active_turn is not None and not self._active_turn.done():
        self._emit_protocol_event(SessionError(
            operation="new", message="Cannot start new session during active turn."
        ))
        return
    try:
        config = self.session.config
        new_session = Session(config=config)
        _configure_rollout_persistence(new_session, config=config)
        await self._activate_session(new_session)
    except Exception as exc:
        self._emit_protocol_event(SessionError(operation="new", message=str(exc)))
```

---

### 2.7 TypeScript: `tui/src/protocol/types.ts`

Add event types:

```typescript
export type SessionSummaryItem = {
  thread_id: string;
  status: "closed" | "incomplete";
  turn_count: number;
  token_total: number;
  last_user_message: string | null;
  date: string;
};

export type SessionListedEvent = {
  type: "session.listed";
  sessions: SessionSummaryItem[];
};

export type SessionStatusEvent = {
  type: "session.status";
  thread_id: string;
  turn_count: number;
  input_tokens: number;
  output_tokens: number;
};

export type SlashUnknownEvent = {
  type: "slash.unknown";
  command: string;
};

export type SlashBlockedEvent = {
  type: "slash.blocked";
  command: string;
  reason: "active_turn";
};

export type SessionErrorEvent = {
  type: "session.error";
  operation: "resume" | "new" | "list";
  message: string;
};
```

Extend `ProtocolEvent` union with all six.

Add command types:

```typescript
export type SessionResumeCommand = {
  jsonrpc: "2.0";
  method: "session.resume";
  params: { thread_id: string };
};

export type SessionNewCommand = {
  jsonrpc: "2.0";
  method: "session.new";
  params: Record<string, never>;
};
```

Extend `Command` union with both.

---

### 2.8 TypeScript: `tui/src/protocol/transports/stdio.ts`

**Parser — add cases to `isProtocolEvent`:**

```typescript
case "session.listed":
  return isRecord(value) && Array.isArray(value["sessions"]);
case "session.status":
  return isString(threadId) && isNumber(value["turn_count"])
    && isNumber(value["input_tokens"]) && isNumber(value["output_tokens"]);
case "slash.unknown":
  return isString(value["command"]);
case "slash.blocked":
  return isString(value["command"]) && value["reason"] === "active_turn";
case "session.error":
  return (
    (value["operation"] === "resume" || value["operation"] === "new"
      || value["operation"] === "list") && isString(value["message"])
  );
```

`session.listed` validates the outer shape only at the transport boundary.
Per-row `sessions[]` validation is owned by a small `app.tsx` normalizer helper
(`toSessionSummaryItems`) before modal state is updated; invalid rows are dropped.
This keeps transport parsing lean while making UI-state assumptions explicit.

**Writer — add to `StdioWriter`:**

```typescript
sendSessionResume(threadId: string): void {
  this.write({ jsonrpc: "2.0", method: "session.resume", params: { thread_id: threadId } });
}

sendSessionNew(): void {
  this.write({ jsonrpc: "2.0", method: "session.new", params: {} });
}
```

---

### 2.9 TypeScript: `tui/src/protocol/writer.ts`

Add to `ProtocolWriter` interface:

```typescript
sendSessionResume(threadId: string): void;
sendSessionNew(): void;
```

Any class or mock implementing `ProtocolWriter` must add these methods or typecheck
will fail. Known affected file: `tui/src/__tests__/index.test.ts` (MockWriter at
line 48) — stub both as no-ops in the mock.

---

### 2.10 TypeScript: `tui/src/hooks/useTurns.ts` — thread reset fix

Current `thread.started` reducer only updates `threadId`:

```typescript
case "thread.started":
  return { ...state, threadId: event.thread_id };
```

Fix: reset `turns` when switching to a different (non-null) thread:

```typescript
case "thread.started":
  if (state.threadId !== null && state.threadId !== event.thread_id) {
    return { threadId: event.thread_id, turns: [] };
  }
  return { ...state, threadId: event.thread_id };
```

Edge cases:
- `null → id` (startup): no reset, turns is already `[]`. Correct.
- `id → same id` (reconnect without switch): no reset. Correct.
- `id → different id` (resume/new): reset. Correct.

Note: the same-thread resume path that could produce `id → same id` after
`_activate_session` is prevented at the bridge layer (§2.6 guard). The reducer fix
handles the general case; the bridge guard is defence-in-depth.

---

### 2.11 TypeScript: `tui/src/hooks/useSystemNotices.ts` (new)

Collects bridge-level feedback events as displayable notice strings. These are not
agent turns and must not be mixed into the turns list.

```typescript
export type SystemNotice = {
  id: string;  // stable key for React rendering
  text: string;
};

export function useSystemNotices(events: readonly ProtocolEvent[]): SystemNotice[]
```

Converts:
- `session.status` → formatted string with thread_id, turns, tokens
- `slash.unknown` → `"Unknown command: /<command>"`
- `slash.blocked` → `"/<command> is not available during an active turn."`
- `session.error` → `"Session error (${operation}): ${message}"`

Other event types are ignored. Notices accumulate; cleared only on full event reset.

---

### 2.12 TypeScript: `tui/src/hooks/useSlashCompletion.ts` (new)

Pure state hook that drives the slash command autocomplete popup. Takes the current
input value, returns popup state. Has no side effects and no protocol coupling — it
only knows about the static command catalog.

**Static command catalog** (exported for use in tests and the popup component):

```typescript
export type SlashCommandDef = {
  command: string;   // without leading slash, e.g. "resume"
  description: string;
};

export const SLASH_COMMANDS: readonly SlashCommandDef[] = [
  { command: "resume", description: "resume a saved chat" },
  { command: "status", description: "show current session token usage" },
  { command: "new",    description: "start a new chat" },
];
```

**Hook signature:**

```typescript
export type SlashCompletionState = {
  isOpen: boolean;
  matches: readonly SlashCommandDef[];
  selectedIndex: number;
};

export type SlashCompletionActions = {
  moveUp: () => void;
  moveDown: () => void;
  complete: () => string | null;  // returns completed input string or null if empty
  dismiss: () => void;
};

export function useSlashCompletion(
  value: string,
): SlashCompletionState & SlashCompletionActions
```

**Logic:**

- `isOpen`: `value.startsWith("/") && !value.includes(" ")` — open only while typing
  the command name, not while typing arguments.
- `matches`: filter `SLASH_COMMANDS` where `cmd.command.startsWith(typed.toLowerCase())`
  where `typed = value.slice(1)`.
- `selectedIndex`: clamped to `[0, matches.length - 1]`, reset to `0` whenever
  `matches` changes.
- `complete()`: returns `"/${matches[selectedIndex].command} "` (trailing space ready
  for arguments), or `null` if `matches` is empty.
- `dismiss()`: internal override forces `isOpen` false until `value` changes.

**Why this is a hook and not part of `computeKeyEvent`:**

`computeKeyEvent` is a pure function with no knowledge of the command catalog. Keeping
it pure preserves all existing tests. The popup is an independent concern layered on
top via `useInput` interception in `InputArea`.

---

### 2.13 TypeScript: `tui/src/components/SlashCommandPopup.tsx` (new)

Ink component that renders the autocomplete popup. Displayed inside `InputArea` above
the prompt line. Props:

```typescript
type Props = {
  matches: readonly SlashCommandDef[];
  selectedIndex: number;
};
```

Renders one row per match. Selected row is highlighted (inverse). Each row:
`/<command>  <description>`. Returns `null` when `matches` is empty. No keyboard
handling — all key events are managed in `InputArea`.

Example render when typing `/re`:
```
┌──────────────────────────────────┐
│ /resume  resume a saved chat     │  <- highlighted
│ > /re_                           │
└──────────────────────────────────┘
```

---

### 2.14 TypeScript: `tui/src/components/InputArea.tsx` — autocomplete integration

**Changes:**

1. Import `useSlashCompletion` and `SlashCommandPopup`.
2. Call `useSlashCompletion(editorState.value)` inside the component.
3. Add popup key intercept in `useInput` **before** the existing `computeKeyEvent`
   call — `computeKeyEvent` is unchanged:

```typescript
useInput((input, key) => {
  // existing ctrl+c / ctrl+x handlers unchanged

  // Slash popup intercept — runs before computeKeyEvent
  if (slashCompletion.isOpen) {
    if (key.upArrow && !key.ctrl && !key.meta) {
      slashCompletion.moveUp();
      return;
    }
    if (key.downArrow && !key.ctrl && !key.meta) {
      slashCompletion.moveDown();
      return;
    }
    if (key.return || input === "\t") {
      const completed = slashCompletion.complete();
      if (completed !== null) {
        setEditorState({
          ...editorStateRef.current,
          value: completed,
          cursorIndex: completed.length,
          historyIndex: null,
          draftBeforeHistory: "",
        });
      }
      // Tab with no matches falls through to computeKeyEvent; return only on success
      if (completed !== null) return;
    }
    if (key.escape) {
      slashCompletion.dismiss();
      return;
    }
    // Any other key falls through to normal computeKeyEvent handling
  }

  const result = computeKeyEvent(editorStateRef.current, input, key, disabled);
  // ... existing switch unchanged
});
```

Tab with no matches falls through to `computeKeyEvent` rather than being swallowed
silently. Tab with a match completes and returns early.

4. Render `SlashCommandPopup` above the prompt line inside the existing `Box`:

```tsx
<Box borderStyle="single" paddingX={1} flexDirection="column">
  {slashCompletion.isOpen && slashCompletion.matches.length > 0 ? (
    <SlashCommandPopup
      matches={slashCompletion.matches}
      selectedIndex={slashCompletion.selectedIndex}
    />
  ) : null}
  {disabled ? (
    <Text color="yellow">Input disabled ...</Text>
  ) : (
    <>
      <Text>{before}</Text>
      <Text inverse>{atCursor}</Text>
      {after.length > 0 ? <Text>{after}</Text> : null}
    </>
  )}
</Box>
```

**Key conflict note:** `↑`/`↓` are normally used for history recall. When the popup
is open, these are intercepted before `computeKeyEvent` sees them, suspending history
navigation while the popup is visible. This matches standard terminal autocomplete
behavior.

---

### 2.15 TypeScript: `tui/src/components/SessionPickerModal.tsx` (new)

Ink component. Displayed when `session.listed` is received. Props:

```typescript
type Props = {
  sessions: SessionSummaryItem[];
  onSelect: (threadId: string) => void;
  onDismiss: () => void;
};
```

Renders a bordered box with:
- Title: "Resume a previous session"
- Rows: `date  thread_id(truncated)  turns=N  tokens=N  status  last_user_message(truncated)`
- Selected row highlighted
- Footer: `[Enter] resume  [Esc] cancel`

Keyboard:
- `↑` / `k`: move selection up
- `↓` / `j`: move selection down
- `Enter`: call `onSelect(selectedThreadId)`
- `Esc`: call `onDismiss()`

No search/filter in v1. No pagination — list is capped at 500 by the bridge, and the
current session is filtered out by the bridge before emission.

---

### 2.16 TypeScript: `tui/src/app.tsx`

Wire new behavior:

1. On `session.listed` event: normalize rows via `toSessionSummaryItems(payload)`
   and open modal with only valid rows.
2. On `session.status` / `slash.*` / `session.error`: feed to `useSystemNotices`.
3. `SessionPickerModal.onSelect(threadId)` → `writer.sendSessionResume(threadId)`, close modal.
4. `SessionPickerModal.onDismiss()` → close modal (no command sent).
5. Disable `InputArea` while picker modal is open.
6. Render `SystemNotice[]` as dimmed lines above the input area.

Note: the slash autocomplete popup is internal to `InputArea` and requires no wiring
in `app.tsx`.

---

### 2.17 Tests for PR 2

**Python — `tests/core/test_tui_bridge.py` additions:**

- `/status` emits `session.status` with correct counts.
- `/status` via JSON-RPC during a mocked active turn still emits `session.status`
  (bridge-level contract; not reachable through TUI input while turn is active).
- `/resume` emits `session.listed` excluding current thread_id (mock `list_sessions`).
- `/resume` via JSON-RPC during active turn emits `slash.blocked`.
- `/resume` with no sessions returns empty `session.listed`.
- `/new` swaps session, emits new `thread.started` with different thread_id.
- `/new` via JSON-RPC during active turn emits `slash.blocked`.
- `session.resume` with valid thread_id replays rollout, swaps session, emits new
  `thread.started`.
- `session.resume` with current session's thread_id emits `session.error` (same-thread
  guard).
- `session.resume` with missing thread_id emits `session.error`.
- `session.resume` with unknown thread_id emits `session.error`.
- `session.resume` during active turn emits `session.error`.
- `session.resume` when `_activate_session` raises emits `session.error` (no crash).
- `/new` when `_activate_session` raises emits `session.error` (no crash).
- After `_activate_session`, `_pending_approvals` is cleared.
- Unknown slash command emits `slash.unknown`.
- `list_sessions` raising during `/resume` emits `session.error` (no crash).

**TypeScript — `tui/src/__tests__/reader.test.ts` additions:**

- Parse all six new event shapes and confirm they pass `isProtocolEvent`.
- Confirm `session.listed` with empty sessions array is valid.
- Confirm `session.listed` with non-array sessions is rejected.
- Confirm `session.listed` with mixed valid/invalid row items still parses at transport
  boundary (outer-shape only); row filtering is covered by `app` normalizer tests.

**TypeScript — `tui/src/__tests__/app.test.tsx` additions:**

- `toSessionSummaryItems` keeps valid rows and drops malformed rows.
- `session.listed` with all malformed rows opens picker with empty state (no crash).

**TypeScript — `tui/src/__tests__/writer.test.ts` additions:**

- `sendSessionResume("abc")` writes correct JSON-RPC line.
- `sendSessionNew()` writes correct JSON-RPC line.

**TypeScript — `tui/src/__tests__/useTurns.test.ts` additions:**

- `thread.started` with same thread_id does not reset turns.
- `thread.started` with different thread_id from non-null state resets turns to `[]`.
- `thread.started` from null state (startup) does not reset turns.

**TypeScript — `tui/src/__tests__/useSlashCompletion.test.ts` (new):**

- Empty input: `isOpen` false.
- `/` alone: `isOpen` true, all commands returned.
- `/r`: matches only `resume`.
- `/s`: matches only `status`.
- `/n`: matches only `new`.
- `/x`: no matches, `isOpen` true, `matches` empty.
- `/ ` (slash then space): `isOpen` false.
- `/resume `: `isOpen` false.
- `moveUp` at index 0 stays at 0 (clamp, no wrap).
- `moveDown` clamps at `matches.length - 1`.
- `selectedIndex` resets to 0 when filter changes.
- `complete()` returns `"/resume "` when `resume` is selected.
- `complete()` returns `null` when `matches` is empty.
- `dismiss()` forces `isOpen` false until value changes.

**TypeScript — `tui/src/__tests__/inputArea.test.ts` additions:**

- Typing `/` opens popup.
- Typing `/r` shows only `resume` in popup.
- `↓` while popup open moves selection, does not trigger history recall.
- `↑` while popup open moves selection up, does not trigger history recall.
- `Tab` while popup open completes to `/resume `.
- `Enter` while popup open completes to selected command.
- `Esc` while popup open closes popup, input value unchanged.
- `Tab` while popup open with no matches does not complete (falls through).
- After completion, typing a space does not reopen popup.
- `↑`/`↓` when popup is closed still trigger history recall (regression guard).

**TypeScript — `tui/src/__tests__/useSystemNotices.test.ts` (new):**

- `session.status` event produces formatted notice.
- `slash.unknown` event produces notice.
- `slash.blocked` event produces notice.
- `session.error` event produces notice.
- Other event types produce no notice.
- Multiple events accumulate notices.

**TypeScript — `tui/src/__tests__/sessionPickerModal.test.tsx` (new):**

- Renders session rows.
- Arrow key down moves selection.
- Enter calls `onSelect` with selected thread_id.
- Esc calls `onDismiss`.
- Empty sessions list renders gracefully.

---

### 2.18 Files changed in PR 2

**Python:**
```
pycodex/protocol/events.py
pycodex/core/tui_bridge.py
tests/core/test_tui_bridge.py
```

**TypeScript:**
```
tui/src/protocol/types.ts
tui/src/protocol/transports/stdio.ts
tui/src/protocol/writer.ts
tui/src/hooks/useTurns.ts
tui/src/hooks/useSlashCompletion.ts           (new)
tui/src/hooks/useSystemNotices.ts             (new)
tui/src/components/SlashCommandPopup.tsx      (new)
tui/src/components/SessionPickerModal.tsx     (new)
tui/src/components/InputArea.tsx
tui/src/app.tsx
tui/src/__tests__/app.test.tsx                (new)
tui/src/__tests__/reader.test.ts
tui/src/__tests__/writer.test.ts
tui/src/__tests__/useTurns.test.ts
tui/src/__tests__/useSlashCompletion.test.ts  (new)
tui/src/__tests__/useSystemNotices.test.ts    (new)
tui/src/__tests__/inputArea.test.ts
tui/src/__tests__/sessionPickerModal.test.tsx (new)
tui/src/__tests__/index.test.ts               (MockWriter stub for new methods)
```

**Docs:**
```
docs/ai/system-map.md
```

### 2.19 Quality gates for PR 2

```
ruff check . --fix && ruff format .
mypy --strict pycodex/
pytest tests/ -v
cd tui && npm run typecheck
cd tui && npm run lint
cd tui && npm test
```

---

## Acceptance Criteria

Both PRs merged and all gates passing, plus manual verification:

1. `pycodex --tui-mode` (fresh session): type `/status` → `session.status` event
   emitted with correct thread_id and zero counts.
2. After one turn: `/status` → non-zero turn_count and token counts.
3. Typing `/` opens autocomplete popup showing all three commands with descriptions.
4. Typing `/r` filters popup to only `resume`; `Tab` or `Enter` completes to `/resume `.
5. `↑`/`↓` navigate the popup; `Esc` dismisses without completing.
6. `Tab` with no matches (e.g. `/xyz`) does not autocomplete and the input text
   remains unchanged.
7. `↑`/`↓` still navigate history when popup is closed (regression).
8. `/resume` with no prior sessions → `session.listed` with empty array; picker shows
   empty state gracefully.
9. `/resume` with prior sessions → picker opens; current session is absent from the
   list; selecting another session loads its history.
10. First prompt after resume continues the replayed conversation (session history
    included in model context).
11. `/new` → new `thread.started` with different thread_id; turns list clears.
12. Sending `session.resume` with the active thread_id via JSON-RPC → `session.error`,
    no session mutation. (Bridge-level test only; not reachable via TUI input.)
13. Sending `session.resume` or slash commands via JSON-RPC during a mocked active turn
    → correct `session.error` or `slash.blocked`. (Bridge-level test only.)
14. Any handler exception → `session.error` emitted; bridge loop continues. (Verified
    by injecting a fault in tests.)
15. `session.resume` with unknown thread_id → `session.error` notice shown, no crash.
16. `--tui-mode --resume <id>`: `thread.started` carries the resumed session's
    thread_id (not a random UUID). [Validates PR 1 bug fix.]

---

## Open Questions (Decide Before Implementing)

1. **Notice display placement in TUI:** dimmed lines above input, or ephemeral banner
   that fades? The proposal uses notices as persistent lines; banner would be simpler
   to implement but less discoverable.

2. **`session.listed` with many sessions:** v1 caps at 500 in the bridge call.
   If replay of open sessions is too slow for users with large histories, add a
   fast-path flag to `list_sessions` that skips replay and returns incomplete sessions
   with zero usage. Decide post v1 based on actual feedback.

3. **Picker row format:** the current design truncates `thread_id` and
   `last_user_message`. Should threads have human-readable names (the upstream
   supports `/rename`)? Defer to a future `/rename` command.

---

## Wave R3 Plan (Selected Scope: Items 2 + 3, Trimmed)

### Scope

Implement only:
1. **Session metadata contract upgrade** for resume rows with:
   - `updated_at`
   - `size_bytes`
2. **Resume list presentation upgrade** toward Claude-style rows.

Explicitly out of scope for this wave:
- `git_branch` and `cwd` fields.
- Current-worktree grouping.
- Search input in picker (follow-up wave).
- Cursor-based pagination and backend query paging.
- Session renaming/forking.

### R3.1 Contract changes (Python + TUI, atomic)

Upgrade `SessionSummary` payload from:
- `thread_id`, `status`, `turn_count`, `token_total`, `last_user_message`, `date`

to include:
- `updated_at: str` (ISO 8601 UTC; source for "1 week ago")
- `size_bytes: int` (rollout file size)

Files:
- `pycodex/protocol/events.py`
- `tui/src/protocol/types.ts`
- `tui/src/protocol/transports/stdio.ts` (runtime shape checks)
- `tui/src/app.tsx` normalizer for `session.listed`
- `tui/src/__tests__/reader.test.ts`
- `tui/src/__tests__/app.test.tsx`

### R3.2 Session metadata sourcing

In `pycodex/core/session_store.py`, enrich `SessionSummaryRecord` and `list_sessions`:
- `size_bytes` from `path.stat().st_size`.
- `updated_at`:
  - closed session: `session_closed.closed_at`
  - incomplete session: file mtime converted to ISO 8601 UTC.
- Keep deterministic fallback values for legacy rollouts.

Files:
- `pycodex/core/session_store.py`
- `tests/core/test_session_store.py`
- `tests/core/test_tui_bridge.py` (bridge emits enriched session rows)

### R3.3 Resume picker presentation upgrade

Upgrade `SessionPickerModal` to render richer rows with 5-row windowing preserved:
- Header: `Resume Session (X of Y)` where X is selected index.
- Two-line row format:
  - line 1: prompt preview (`last_user_message` fallback text if empty)
  - line 2: `relative_time · size` (e.g. `1 week ago · 619.7KB`)
- Navigation:
  - existing up/down/j/k semantics preserved.
  - scrolling window advances as selection moves beyond visible range.

Files:
- `tui/src/components/SessionPickerModal.tsx`
- `tui/src/__tests__/sessionPickerModal.test.tsx`

### R3.4 Verification gates

Python:
```bash
.venv/bin/ruff check . --fix
.venv/bin/ruff format .
.venv/bin/mypy --strict pycodex/
.venv/bin/pytest tests/core/test_session_store.py -q
.venv/bin/pytest tests/core/test_tui_bridge.py -q
.venv/bin/pytest tests/protocol/test_events.py -q
```

TUI:
```bash
cd tui && npm run typecheck
cd tui && npm run lint
cd tui && npm test -- --runInBand --findRelatedTests \
  src/components/SessionPickerModal.tsx \
  src/app.tsx \
  src/protocol/types.ts \
  src/protocol/transports/stdio.ts
```

### R3 acceptance criteria

1. `/resume` rows include `updated_at` and `size_bytes` in protocol payload.
2. Legacy rollouts without new metadata still list successfully (null-safe rendering).
3. Picker shows max 5 rows at once and scrolls while moving selection.
4. Picker row second line shows relative time and humanized size.
5. No regression in resume/select behavior or `session.resume` command wiring.

### R3 completion status

- Implemented in code and tests.
- Hard gates passed:
  - `.venv/bin/ruff check . --fix`
  - `.venv/bin/ruff format .`
  - `.venv/bin/mypy --strict pycodex/`
  - `.venv/bin/pytest tests -v`
  - `cd tui && npm run typecheck`
  - `cd tui && npm run lint`
  - `cd tui && npm test`
