# TUI Shell-Like Input Editor

## Goal

Replace the append-only input box in `src/components/InputArea.tsx` with a
line-editor that supports cursor movement, point edits, and prompt history —
matching standard terminal-shell UX.

---

## Context

**Primary file modified:** `tui/src/components/InputArea.tsx`
**Test file modified:** `tui/src/__tests__/inputArea.test.ts` (already exists)
**New files:** none
**TypeScript flags to respect:** `strict`, `exactOptionalPropertyTypes`,
`noUncheckedIndexedAccess`

The Ink `useInput` mock in `src/__mocks__/ink.ts` is a no-op, so all
behaviour tests must exercise exported pure functions directly — not the
component's `useInput` handler.

---

## Behaviour Added

| Key | Action |
|---|---|
| Up | Recall older history entry (newest-first). First press saves draft. |
| Down | Move toward newer entry; final Down restores pre-history draft. |
| Left | Move cursor one character left, clamped at 0. |
| Right | Move cursor one character right, clamped at `value.length`. |
| Printable char | Insert at cursor; advances cursor. Exits history mode. |
| Backspace | Delete character before cursor. Exits history mode. |
| Delete | Terminal-compat mode: backward delete (same as Backspace). Exits history mode. |
| Enter | Trim and submit non-empty value; store in history; clear editor. |
| Enter (empty/whitespace) | No-op; nothing stored in history. |
| Ctrl+C / Ctrl+X | Unchanged — handled before all editor logic. |

History is bounded to 100 entries (oldest dropped when cap is reached).

---

## Step 1 — New Types and Constants

Add after the existing `BRACKETED_PASTE_START` / `BRACKETED_PASTE_END`
constants and before the existing exported functions.

```ts
type EditorState = {
  value: string;
  cursorIndex: number;         // invariant: 0 <= cursorIndex <= value.length
  history: readonly string[];  // oldest at [0], newest at [length-1]
  historyIndex: number | null; // null = not in history-navigation mode
  draftBeforeHistory: string;  // saved draft when history mode is entered
};

export const HISTORY_MAX = 100;

export const INITIAL_EDITOR_STATE: EditorState = {
  value: "",
  cursorIndex: 0,
  history: [],
  historyIndex: null,
  draftBeforeHistory: "",
};
```

`EditorState` is **not** exported — it is an internal implementation detail.
Only `HISTORY_MAX` and `INITIAL_EDITOR_STATE` are exported (tests need them
to construct fixture states).

---

## Step 2 — Pure Helper Functions

All exported. Place them after `isSubmitInput` and before the `InputArea`
component. Each is a pure transform with no side effects.

### `insertAtCursor`

```ts
export function insertAtCursor(
  value: string,
  cursor: number,
  chunk: string,
): { value: string; cursorIndex: number } {
  return {
    value: value.slice(0, cursor) + chunk + value.slice(cursor),
    cursorIndex: cursor + chunk.length,
  };
}
```

### `deleteBackward`

```ts
export function deleteBackward(
  value: string,
  cursor: number,
): { value: string; cursorIndex: number } {
  if (cursor === 0) return { value, cursorIndex: 0 };
  return {
    value: value.slice(0, cursor - 1) + value.slice(cursor),
    cursorIndex: cursor - 1,
  };
}
```

### `deleteForward`

```ts
export function deleteForward(
  value: string,
  cursor: number,
): { value: string; cursorIndex: number } {
  if (cursor >= value.length) return { value, cursorIndex: cursor };
  return {
    value: value.slice(0, cursor) + value.slice(cursor + 1),
    cursorIndex: cursor,
  };
}
```

### `moveCursorLeft`

```ts
export function moveCursorLeft(cursor: number): number {
  return Math.max(0, cursor - 1);
}
```

### `moveCursorRight`

```ts
export function moveCursorRight(cursor: number, valueLength: number): number {
  return Math.min(valueLength, cursor + 1);
}
```

### `recallHistoryUp`

History is oldest-first. Up walks the index downward (toward index 0). On the
first Up, the current draft is saved into `draftBeforeHistory`.

```ts
export function recallHistoryUp(state: EditorState): EditorState {
  const { history, historyIndex, value } = state;
  if (history.length === 0) return state;

  if (historyIndex === null) {
    const newIndex = history.length - 1;
    const entry = history[newIndex];
    if (entry === undefined) return state;
    return {
      ...state,
      draftBeforeHistory: value,
      historyIndex: newIndex,
      value: entry,
      cursorIndex: entry.length,
    };
  }

  if (historyIndex === 0) return state; // already at oldest

  const newIndex = historyIndex - 1;
  const entry = history[newIndex];
  if (entry === undefined) return state;
  return {
    ...state,
    historyIndex: newIndex,
    value: entry,
    cursorIndex: entry.length,
  };
}
```

### `recallHistoryDown`

Down walks the index upward (toward `length - 1`). One press past the newest
entry restores the draft and sets `historyIndex` back to `null`.

```ts
export function recallHistoryDown(state: EditorState): EditorState {
  const { history, historyIndex, draftBeforeHistory } = state;
  if (historyIndex === null) return state; // already in draft mode

  if (historyIndex === history.length - 1) {
    return {
      ...state,
      historyIndex: null,
      value: draftBeforeHistory,
      cursorIndex: draftBeforeHistory.length,
    };
  }

  const newIndex = historyIndex + 1;
  const entry = history[newIndex];
  if (entry === undefined) return state;
  return {
    ...state,
    historyIndex: newIndex,
    value: entry,
    cursorIndex: entry.length,
  };
}
```

### `pushHistoryEntry`

Appends and trims to `maxEntries` from the end (drops oldest).

```ts
export function pushHistoryEntry(
  history: readonly string[],
  text: string,
  maxEntries: number,
): readonly string[] {
  const next = [...history, text];
  return next.length > maxEntries ? next.slice(next.length - maxEntries) : next;
}
```

---

## Step 3 — `computeKeyEvent` (exported)

This is the single testable unit that maps `(state, input, key, disabled)` to
a result. It does **not** handle Ctrl+C or Ctrl+X — those are handled in the
`useInput` closure before `computeKeyEvent` is called, using the existing
`handleCtrlC` / `handleCtrlX` functions.

### Local types (not exported)

```ts
type KeyEventResult =
  | { type: "noop" }
  | { type: "state"; state: EditorState }
  | { type: "submit"; text: string; state: EditorState };

interface MinimalKey {
  ctrl: boolean;
  meta: boolean;
  return: boolean;
  backspace: boolean;
  delete: boolean;
  upArrow: boolean;
  downArrow: boolean;
  leftArrow: boolean;
  rightArrow: boolean;
}
```

`MinimalKey` is defined locally so tests can construct plain objects without
importing Ink. Ink's `Key` type satisfies this interface structurally, so
passing real `Key` objects from `useInput` requires no casting.

### Function

```ts
export function computeKeyEvent(
  state: EditorState,
  input: string,
  key: MinimalKey,
  disabled: boolean,
): KeyEventResult {
  if (disabled) return { type: "noop" };

  // Submit
  if (isSubmitInput(input, key.return)) {
    const text = state.value.trim();
    if (text.length === 0) return { type: "noop" };
    return {
      type: "submit",
      text,
      state: {
        value: "",
        cursorIndex: 0,
        history: pushHistoryEntry(state.history, text, HISTORY_MAX),
        historyIndex: null,
        draftBeforeHistory: "",
      },
    };
  }

  // Arrow keys — plain only; Ctrl/Meta-modified variants fall through to noop
  if (key.upArrow && !key.ctrl && !key.meta) {
    return { type: "state", state: recallHistoryUp(state) };
  }
  if (key.downArrow && !key.ctrl && !key.meta) {
    return { type: "state", state: recallHistoryDown(state) };
  }
  if (key.leftArrow && !key.ctrl && !key.meta) {
    return {
      type: "state",
      state: { ...state, cursorIndex: moveCursorLeft(state.cursorIndex) },
    };
  }
  if (key.rightArrow && !key.ctrl && !key.meta) {
    return {
      type: "state",
      state: {
        ...state,
        cursorIndex: moveCursorRight(state.cursorIndex, state.value.length),
      },
    };
  }

  // Backspace / Delete — both exit history mode
  if (key.backspace) {
    return {
      type: "state",
      state: {
        ...state,
        ...deleteBackward(state.value, state.cursorIndex),
        historyIndex: null,
        draftBeforeHistory: "",
      },
    };
  }
  if (key.delete) {
    // Many terminals surface Backspace/Delete via `key.delete`.
    // Use backward delete for consistent shell-like editing.
    return {
      type: "state",
      state: {
        ...state,
        ...deleteBackward(state.value, state.cursorIndex),
        historyIndex: null,
        draftBeforeHistory: "",
      },
    };
  }

  // Drop remaining modifier / empty events
  if (key.ctrl || key.meta || input.length === 0) {
    return { type: "noop" };
  }

  // Printable text — exits history mode, inserts at cursor
  const sanitized = sanitizeInputChunk(input);
  if (sanitized.length === 0) return { type: "noop" };

  return {
    type: "state",
    state: {
      ...state,
      ...insertAtCursor(state.value, state.cursorIndex, sanitized),
      historyIndex: null,
      draftBeforeHistory: "",
    },
  };
}
```

---

## Step 4 — Update `InputArea` Component

### 4a. State

Replace the single `useState("")` with:

```ts
const [editorState, setEditorState] = useState<EditorState>(INITIAL_EDITOR_STATE);
```

### 4b. `useEffect` for disabled reset

Replace the existing effect. All fields must be reset, not just `value`:

```ts
useEffect(() => {
  if (disabled) {
    setEditorState(INITIAL_EDITOR_STATE);
  }
}, [disabled]);
```

### 4c. `useInput` handler

Replace the entire existing `useInput` block:

```ts
useInput((input, key) => {
  // Ctrl+C and Ctrl+X are handled unconditionally before any editor logic.
  if (key.ctrl && input.toLowerCase() === "c") {
    handleCtrlC(hasActiveTurn, { onInterrupt });
    return;
  }
  if (key.ctrl && input.toLowerCase() === "x") {
    handleCtrlX({ onExit });
    return;
  }

  const result = computeKeyEvent(editorState, input, key, disabled);
  switch (result.type) {
    case "submit":
      setEditorState(result.state);
      onSubmit(result.text);
      break;
    case "state":
      setEditorState(result.state);
      break;
    case "noop":
      break;
  }
});
```

### 4d. Render with cursor

The cursor renders as an inverse-highlighted character. When the cursor is at
end-of-line, `value[cursorIndex]` is `undefined` under `noUncheckedIndexedAccess`;
the `?? " "` produces a visible block cursor at EOL.

Replace the existing non-disabled render branch:

```tsx
const before = `> ${editorState.value.slice(0, editorState.cursorIndex)}`;
const atCursor = editorState.value[editorState.cursorIndex] ?? " ";
const after = editorState.value.slice(editorState.cursorIndex + 1);

// in JSX:
<>
  <Text>{before}</Text>
  <Text inverse>{atCursor}</Text>
  {after.length > 0 ? <Text>{after}</Text> : null}
</>
```

The three `<Text>` nodes render inline within the `<Box>` because Ink's
default `flexDirection` is `"row"`.

---

## Step 5 — Tests (`src/__tests__/inputArea.test.ts`)

The four existing `describe` blocks (`sanitizeInputChunk`, `handleCtrlC`,
`handleCtrlX`, `isSubmitInput`) are **unchanged**. Add the following.

### 5a. Updated import block

```ts
import {
  handleCtrlC,
  handleCtrlX,
  isSubmitInput,
  sanitizeInputChunk,
  // new exports:
  computeKeyEvent,
  deleteBackward,
  deleteForward,
  insertAtCursor,
  INITIAL_EDITOR_STATE,
  HISTORY_MAX,
  moveCursorLeft,
  moveCursorRight,
  pushHistoryEntry,
  recallHistoryDown,
  recallHistoryUp,
} from "../components/InputArea.js";
```

### 5b. Key factory helper (add near top of file, after imports)

```ts
function makeKey(overrides: {
  ctrl?: boolean;
  meta?: boolean;
  return?: boolean;
  backspace?: boolean;
  delete?: boolean;
  upArrow?: boolean;
  downArrow?: boolean;
  leftArrow?: boolean;
  rightArrow?: boolean;
} = {}) {
  return {
    ctrl: false,
    meta: false,
    return: false,
    backspace: false,
    delete: false,
    upArrow: false,
    downArrow: false,
    leftArrow: false,
    rightArrow: false,
    ...overrides,
  };
}
```

### 5c. `insertAtCursor` describe block

```ts
describe("insertAtCursor", () => {
  test("inserts at beginning", () => {
    expect(insertAtCursor("hello", 0, "x")).toEqual({ value: "xhello", cursorIndex: 1 });
  });
  test("inserts at middle and advances cursor", () => {
    expect(insertAtCursor("hello", 2, "x")).toEqual({ value: "hexllo", cursorIndex: 3 });
  });
  test("inserts at end", () => {
    expect(insertAtCursor("hello", 5, "x")).toEqual({ value: "hellox", cursorIndex: 6 });
  });
  test("inserts multi-char chunk and advances cursor by chunk length", () => {
    expect(insertAtCursor("hello", 2, "XY")).toEqual({ value: "heXYllo", cursorIndex: 4 });
  });
  test("inserts into empty string", () => {
    expect(insertAtCursor("", 0, "a")).toEqual({ value: "a", cursorIndex: 1 });
  });
});
```

### 5d. `deleteBackward` describe block

```ts
describe("deleteBackward", () => {
  test("is a no-op at cursor 0", () => {
    expect(deleteBackward("hello", 0)).toEqual({ value: "hello", cursorIndex: 0 });
  });
  test("deletes character before cursor at position 1", () => {
    expect(deleteBackward("hello", 1)).toEqual({ value: "ello", cursorIndex: 0 });
  });
  test("deletes character before cursor in middle", () => {
    expect(deleteBackward("hello", 3)).toEqual({ value: "helo", cursorIndex: 2 });
  });
  test("deletes last character when cursor is at end", () => {
    expect(deleteBackward("hello", 5)).toEqual({ value: "hell", cursorIndex: 4 });
  });
});
```

### 5e. `deleteForward` describe block

```ts
describe("deleteForward", () => {
  test("is a no-op when cursor is at end", () => {
    expect(deleteForward("hello", 5)).toEqual({ value: "hello", cursorIndex: 5 });
  });
  test("deletes character at cursor position 0", () => {
    expect(deleteForward("hello", 0)).toEqual({ value: "ello", cursorIndex: 0 });
  });
  test("deletes character at cursor in middle and keeps cursor position", () => {
    expect(deleteForward("hello", 2)).toEqual({ value: "helo", cursorIndex: 2 });
  });
  test("deletes last character when cursor is one before end", () => {
    expect(deleteForward("hello", 4)).toEqual({ value: "hell", cursorIndex: 4 });
  });
});
```

### 5f. `moveCursorLeft` / `moveCursorRight` describe blocks

```ts
describe("moveCursorLeft", () => {
  test("clamps at 0", () => {
    expect(moveCursorLeft(0)).toBe(0);
  });
  test("decrements by 1", () => {
    expect(moveCursorLeft(3)).toBe(2);
  });
});

describe("moveCursorRight", () => {
  test("clamps at value length", () => {
    expect(moveCursorRight(5, 5)).toBe(5);
  });
  test("increments by 1", () => {
    expect(moveCursorRight(3, 5)).toBe(4);
  });
  test("clamps when value is empty", () => {
    expect(moveCursorRight(0, 0)).toBe(0);
  });
});
```

### 5g. `pushHistoryEntry` describe block

```ts
describe("pushHistoryEntry", () => {
  test("appends to empty history", () => {
    expect(pushHistoryEntry([], "hello", 100)).toEqual(["hello"]);
  });
  test("appends to existing history", () => {
    expect(pushHistoryEntry(["a"], "b", 100)).toEqual(["a", "b"]);
  });
  test("drops oldest entry when cap is reached", () => {
    expect(pushHistoryEntry(["a", "b", "c"], "d", 3)).toEqual(["b", "c", "d"]);
  });
  test("does not drop when exactly at cap", () => {
    expect(pushHistoryEntry(["a", "b"], "c", 3)).toEqual(["a", "b", "c"]);
  });
  test("enforces HISTORY_MAX (cap = 100)", () => {
    const full = Array.from({ length: HISTORY_MAX }, (_, i) => String(i));
    const result = pushHistoryEntry(full, "new", HISTORY_MAX);
    expect(result).toHaveLength(HISTORY_MAX);
    expect(result[result.length - 1]).toBe("new");
    expect(result[0]).toBe("1");
  });
});
```

### 5h. `recallHistoryUp` describe block

```ts
describe("recallHistoryUp", () => {
  const withHistory = (entries: string[]) => ({
    ...INITIAL_EDITOR_STATE,
    history: entries,
  });

  test("is a no-op when history is empty", () => {
    const state = withHistory([]);
    expect(recallHistoryUp(state)).toBe(state);
  });

  test("first Up saves draft and recalls newest entry", () => {
    const state = { ...withHistory(["first", "second"]), value: "draft" };
    const result = recallHistoryUp(state);
    expect(result.value).toBe("second");
    expect(result.historyIndex).toBe(1);
    expect(result.draftBeforeHistory).toBe("draft");
    expect(result.cursorIndex).toBe("second".length);
  });

  test("repeated Up moves to older entry", () => {
    const state = {
      ...withHistory(["first", "second"]),
      historyIndex: 1 as number | null,
      value: "second",
      draftBeforeHistory: "draft",
      cursorIndex: 6,
    };
    const result = recallHistoryUp(state);
    expect(result.value).toBe("first");
    expect(result.historyIndex).toBe(0);
    expect(result.cursorIndex).toBe("first".length);
  });

  test("Up is a no-op when already at oldest entry", () => {
    const state = {
      ...withHistory(["first", "second"]),
      historyIndex: 0 as number | null,
      value: "first",
      draftBeforeHistory: "draft",
      cursorIndex: 5,
    };
    expect(recallHistoryUp(state)).toBe(state);
  });

  test("cursor lands at end of recalled entry", () => {
    const state = withHistory(["hello world"]);
    const result = recallHistoryUp(state);
    expect(result.cursorIndex).toBe("hello world".length);
  });
});
```

### 5i. `recallHistoryDown` describe block

```ts
describe("recallHistoryDown", () => {
  const inHistory = (entries: string[], index: number, draft: string) => ({
    ...INITIAL_EDITOR_STATE,
    history: entries,
    historyIndex: index as number | null,
    draftBeforeHistory: draft,
    value: entries[index] ?? "",
    cursorIndex: (entries[index] ?? "").length,
  });

  test("is a no-op when not in history mode", () => {
    expect(recallHistoryDown(INITIAL_EDITOR_STATE)).toBe(INITIAL_EDITOR_STATE);
  });

  test("Down from newest entry restores draft and exits history mode", () => {
    const state = inHistory(["first", "second"], 1, "my draft");
    const result = recallHistoryDown(state);
    expect(result.historyIndex).toBeNull();
    expect(result.value).toBe("my draft");
    expect(result.cursorIndex).toBe("my draft".length);
  });

  test("Down from middle moves to newer entry", () => {
    const state = inHistory(["first", "second", "third"], 0, "draft");
    const result = recallHistoryDown(state);
    expect(result.value).toBe("second");
    expect(result.historyIndex).toBe(1);
    expect(result.cursorIndex).toBe("second".length);
  });
});
```

### 5j. `computeKeyEvent` describe block

```ts
describe("computeKeyEvent", () => {
  const noKey = makeKey();

  test("returns noop when disabled", () => {
    const result = computeKeyEvent(
      { ...INITIAL_EDITOR_STATE, value: "hello", cursorIndex: 5 },
      "a",
      noKey,
      true,
    );
    expect(result.type).toBe("noop");
  });

  test("inserts printable character at cursor", () => {
    const state = { ...INITIAL_EDITOR_STATE, value: "hllo", cursorIndex: 1 };
    const result = computeKeyEvent(state, "e", noKey, false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("hello");
      expect(result.state.cursorIndex).toBe(2);
    }
  });

  test("typed character exits history mode", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      value: "old",
      cursorIndex: 3,
      historyIndex: 0 as number | null,
      history: ["old"],
      draftBeforeHistory: "new",
    };
    const result = computeKeyEvent(state, "x", noKey, false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.historyIndex).toBeNull();
    }
  });

  test("submit trims value and stores in history", () => {
    const state = { ...INITIAL_EDITOR_STATE, value: "  hello  ", cursorIndex: 9 };
    const result = computeKeyEvent(state, "", makeKey({ return: true }), false);
    expect(result.type).toBe("submit");
    if (result.type === "submit") {
      expect(result.text).toBe("hello");
      expect(result.state.history).toContain("hello");
      expect(result.state.value).toBe("");
      expect(result.state.cursorIndex).toBe(0);
      expect(result.state.historyIndex).toBeNull();
    }
  });

  test("submit on empty value is a no-op", () => {
    const result = computeKeyEvent(INITIAL_EDITOR_STATE, "", makeKey({ return: true }), false);
    expect(result.type).toBe("noop");
  });

  test("submit on whitespace-only value is a no-op and does not store history", () => {
    const state = { ...INITIAL_EDITOR_STATE, value: "   ", cursorIndex: 3 };
    const result = computeKeyEvent(state, "", makeKey({ return: true }), false);
    expect(result.type).toBe("noop");
  });

  test("Up arrow triggers history recall", () => {
    const state = { ...INITIAL_EDITOR_STATE, history: ["cmd1"], value: "draft" };
    const result = computeKeyEvent(state, "", makeKey({ upArrow: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("cmd1");
    }
  });

  test("Down arrow calls recallHistoryDown", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      history: ["cmd1"],
      historyIndex: 0 as number | null,
      value: "cmd1",
      cursorIndex: 4,
      draftBeforeHistory: "draft",
    };
    const result = computeKeyEvent(state, "", makeKey({ downArrow: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("draft");
      expect(result.state.historyIndex).toBeNull();
    }
  });

  test("Left arrow decrements cursor", () => {
    const state = { ...INITIAL_EDITOR_STATE, value: "hello", cursorIndex: 3 };
    const result = computeKeyEvent(state, "", makeKey({ leftArrow: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.cursorIndex).toBe(2);
    }
  });

  test("Right arrow increments cursor", () => {
    const state = { ...INITIAL_EDITOR_STATE, value: "hello", cursorIndex: 3 };
    const result = computeKeyEvent(state, "", makeKey({ rightArrow: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.cursorIndex).toBe(4);
    }
  });

  test("Ctrl+Left is a no-op (word-jump not implemented)", () => {
    const state = { ...INITIAL_EDITOR_STATE, value: "hello", cursorIndex: 3 };
    const result = computeKeyEvent(state, "", makeKey({ leftArrow: true, ctrl: true }), false);
    expect(result.type).toBe("noop");
  });

  test("backspace deletes backward and exits history mode", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      value: "hello",
      cursorIndex: 3,
      historyIndex: 0 as number | null,
      history: ["hello"],
      draftBeforeHistory: "",
    };
    const result = computeKeyEvent(state, "", makeKey({ backspace: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("helo");
      expect(result.state.cursorIndex).toBe(2);
      expect(result.state.historyIndex).toBeNull();
    }
  });

  test("backspace at cursor 0 does not change value but exits history mode", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      value: "hello",
      cursorIndex: 0,
      historyIndex: 0 as number | null,
      history: ["hello"],
      draftBeforeHistory: "",
    };
    const result = computeKeyEvent(state, "", makeKey({ backspace: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("hello");
      expect(result.state.cursorIndex).toBe(0);
      expect(result.state.historyIndex).toBeNull();
    }
  });

  test("delete removes character at cursor and exits history mode", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      value: "hello",
      cursorIndex: 2,
      historyIndex: 0 as number | null,
      history: ["hello"],
      draftBeforeHistory: "",
    };
    const result = computeKeyEvent(state, "", makeKey({ delete: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("helo");
      expect(result.state.cursorIndex).toBe(2);
      expect(result.state.historyIndex).toBeNull();
    }
  });

  test("delete at end does not change value but exits history mode", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      value: "hello",
      cursorIndex: 5,
      historyIndex: 0 as number | null,
      history: ["hello"],
      draftBeforeHistory: "",
    };
    const result = computeKeyEvent(state, "", makeKey({ delete: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("hello");
      expect(result.state.historyIndex).toBeNull();
    }
  });

  test("pasted text with paste markers is sanitized before insert", () => {
    const result = computeKeyEvent(
      INITIAL_EDITOR_STATE,
      "\u001b[200~hello\u001b[201~",
      noKey,
      false,
    );
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("hello");
    }
  });

  test("input that sanitizes to empty is a no-op", () => {
    const result = computeKeyEvent(INITIAL_EDITOR_STATE, "\u0007", noKey, false);
    expect(result.type).toBe("noop");
  });
});
```

---

## Step 6 — Import Updates

No new package imports are required. The existing `InputArea.tsx` import line:

```ts
import { useEffect, useState } from "react";
import { Box, Text, useInput } from "ink";
```

covers everything needed. All new types and functions are defined locally in
the file.

---

## Step 7 — Known Limitations

Document these in a comment at the top of the new helpers section; do not fix
in this task.

- **Unicode surrogate pairs / emoji:** `value[cursorIndex]` slices by UTF-16
  code unit. An emoji such as 🔥 occupies two code units and will be split if
  the cursor lands between them. Acceptable for an initial implementation.
- **History is in-memory only:** Resets when the process exits. No persistence.
- **No word-jump:** Ctrl+Left / Ctrl+Right are intentionally dropped as
  no-ops via the `!key.ctrl` guard on arrow handling. Can be added later.
- **Forward delete is terminal-dependent:** This implementation treats
  `key.delete` as backward delete for compatibility with terminals that do not
  reliably distinguish Backspace and Delete.

---

## Step 8 — Validation

Run in order; all four must pass before the task is done.

```sh
cd tui && npm run typecheck
cd tui && npm run lint
cd tui && npm test -- --runInBand --findRelatedTests src/components/InputArea.tsx src/__tests__/inputArea.test.ts
cd tui && npm test
```
