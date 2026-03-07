import {
  computeKeyEvent,
  deleteBackward,
  deleteForward,
  handleSlashPopupKey,
  handleCtrlC,
  handleCtrlX,
  HISTORY_MAX,
  INITIAL_EDITOR_STATE,
  insertAtCursor,
  isSubmitInput,
  moveCursorLeft,
  moveCursorRight,
  normalizeSlashSubmitText,
  pushHistoryEntry,
  resetEditorForDisabled,
  recallHistoryDown,
  recallHistoryUp,
  sanitizeInputChunk,
} from "../components/InputArea.js";

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
  tab?: boolean;
  escape?: boolean;
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
    tab: false,
    escape: false,
    ...overrides,
  };
}

describe("sanitizeInputChunk", () => {
  test("keeps ordinary printable text unchanged", () => {
    expect(sanitizeInputChunk("hello, world")).toBe("hello, world");
  });

  test("strips bracketed paste markers", () => {
    const raw = '\u001b[200~Write 12 short lines about HTTP.\u001b[201~';
    expect(sanitizeInputChunk(raw)).toBe("Write 12 short lines about HTTP.");
  });

  test("removes newlines and control characters from pasted chunks", () => {
    const raw = "line 1\r\nline 2\u0007";
    expect(sanitizeInputChunk(raw)).toBe("line 1line 2");
  });
});

describe("handleCtrlC", () => {
  test("clears input and sends interrupt while turn is active", () => {
    const onClearInput = jest.fn();
    const onInterrupt = jest.fn();

    handleCtrlC(true, { onClearInput, onInterrupt });

    expect(onClearInput).toHaveBeenCalledTimes(1);
    expect(onInterrupt).toHaveBeenCalledTimes(1);
  });

  test("clears input but does not interrupt when no turn is active", () => {
    const onClearInput = jest.fn();
    const onInterrupt = jest.fn();

    handleCtrlC(false, { onClearInput, onInterrupt });

    expect(onClearInput).toHaveBeenCalledTimes(1);
    expect(onInterrupt).not.toHaveBeenCalled();
  });
});

describe("handleCtrlX", () => {
  test("exits directly", () => {
    const onExit = jest.fn();

    handleCtrlX({ onExit });

    expect(onExit).toHaveBeenCalledTimes(1);
  });
});

describe("isSubmitInput", () => {
  test("submits when key return is set", () => {
    expect(isSubmitInput("", true)).toBe(true);
  });

  test("submits on bare newline fallback when key metadata is missing", () => {
    expect(isSubmitInput("\n", false)).toBe(true);
    expect(isSubmitInput("\r", false)).toBe(true);
    expect(isSubmitInput("\r\n", false)).toBe(true);
  });

  test("does not submit for pasted text containing newlines", () => {
    expect(isSubmitInput("line 1\nline 2", false)).toBe(false);
    expect(isSubmitInput("\u001b[200~line 1\nline 2\u001b[201~", false)).toBe(
      false,
    );
  });
});

describe("insertAtCursor", () => {
  test("inserts at beginning", () => {
    expect(insertAtCursor("hello", 0, "x")).toEqual({
      value: "xhello",
      cursorIndex: 1,
    });
  });

  test("inserts at middle and advances cursor", () => {
    expect(insertAtCursor("hello", 2, "x")).toEqual({
      value: "hexllo",
      cursorIndex: 3,
    });
  });

  test("inserts at end", () => {
    expect(insertAtCursor("hello", 5, "x")).toEqual({
      value: "hellox",
      cursorIndex: 6,
    });
  });

  test("inserts multi-char chunk and advances cursor by chunk length", () => {
    expect(insertAtCursor("hello", 2, "XY")).toEqual({
      value: "heXYllo",
      cursorIndex: 4,
    });
  });

  test("inserts into empty string", () => {
    expect(insertAtCursor("", 0, "a")).toEqual({ value: "a", cursorIndex: 1 });
  });
});

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

describe("resetEditorForDisabled", () => {
  test("clears transient editor state but preserves history", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      value: "draft",
      cursorIndex: 5,
      history: ["first", "second"],
      historyIndex: 1,
      draftBeforeHistory: "draft",
    };

    expect(resetEditorForDisabled(state)).toEqual({
      ...INITIAL_EDITOR_STATE,
      history: ["first", "second"],
    });
  });
});

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
      historyIndex: 1,
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
      historyIndex: 0,
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

describe("recallHistoryDown", () => {
  const inHistory = (entries: string[], index: number, draft: string) => ({
    ...INITIAL_EDITOR_STATE,
    history: entries,
    historyIndex: index,
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
      historyIndex: 0,
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
    const result = computeKeyEvent(
      INITIAL_EDITOR_STATE,
      "",
      makeKey({ return: true }),
      false,
    );
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
      historyIndex: 0,
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
    const result = computeKeyEvent(
      state,
      "",
      makeKey({ leftArrow: true, ctrl: true }),
      false,
    );
    expect(result.type).toBe("noop");
  });

  test("backspace deletes backward and exits history mode", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      value: "hello",
      cursorIndex: 3,
      historyIndex: 0,
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
      historyIndex: 0,
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

  test("delete performs backward delete and exits history mode", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      value: "hello",
      cursorIndex: 2,
      historyIndex: 0,
      history: ["hello"],
      draftBeforeHistory: "",
    };
    const result = computeKeyEvent(state, "", makeKey({ delete: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("hllo");
      expect(result.state.cursorIndex).toBe(1);
      expect(result.state.historyIndex).toBeNull();
    }
  });

  test("delete at end deletes last character", () => {
    const state = {
      ...INITIAL_EDITOR_STATE,
      value: "hello",
      cursorIndex: 5,
      historyIndex: 0,
      history: ["hello"],
      draftBeforeHistory: "",
    };
    const result = computeKeyEvent(state, "", makeKey({ delete: true }), false);
    expect(result.type).toBe("state");
    if (result.type === "state") {
      expect(result.state.value).toBe("hell");
      expect(result.state.cursorIndex).toBe(4);
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

describe("handleSlashPopupKey", () => {
  test("up/down arrows are intercepted for popup navigation", () => {
    const callbacks = {
      complete: jest.fn(() => "/resume "),
      dismiss: jest.fn(),
      selectNext: jest.fn(),
      selectPrevious: jest.fn(),
    };

    const upResult = handleSlashPopupKey(true, makeKey({ upArrow: true }), callbacks);
    const downResult = handleSlashPopupKey(
      true,
      makeKey({ downArrow: true }),
      callbacks,
    );

    expect(upResult).toEqual({ handled: true, completion: null, submit: false });
    expect(downResult).toEqual({ handled: true, completion: null, submit: false });
    expect(callbacks.selectPrevious).toHaveBeenCalledTimes(1);
    expect(callbacks.selectNext).toHaveBeenCalledTimes(1);
  });

  test("enter completes and marks submit", () => {
    const callbacks = {
      complete: jest.fn(() => "/resume "),
      dismiss: jest.fn(),
      selectNext: jest.fn(),
      selectPrevious: jest.fn(),
    };

    const result = handleSlashPopupKey(true, makeKey({ return: true }), callbacks);

    expect(result).toEqual({ handled: true, completion: "/resume ", submit: true });
    expect(callbacks.complete).toHaveBeenCalledTimes(1);
  });

  test("tab falls through when no completion is available", () => {
    const callbacks = {
      complete: jest.fn(() => null),
      dismiss: jest.fn(),
      selectNext: jest.fn(),
      selectPrevious: jest.fn(),
    };

    const result = handleSlashPopupKey(true, makeKey({ tab: true }), callbacks);

    expect(result).toEqual({ handled: false, completion: null, submit: false });
    expect(callbacks.complete).toHaveBeenCalledTimes(1);
  });

  test("escape dismisses popup", () => {
    const callbacks = {
      complete: jest.fn(() => "/resume "),
      dismiss: jest.fn(),
      selectNext: jest.fn(),
      selectPrevious: jest.fn(),
    };

    const result = handleSlashPopupKey(true, makeKey({ escape: true }), callbacks);

    expect(result).toEqual({ handled: true, completion: null, submit: false });
    expect(callbacks.dismiss).toHaveBeenCalledTimes(1);
  });

  test("when popup is closed, keys fall through", () => {
    const callbacks = {
      complete: jest.fn(() => "/resume "),
      dismiss: jest.fn(),
      selectNext: jest.fn(),
      selectPrevious: jest.fn(),
    };

    const result = handleSlashPopupKey(false, makeKey({ upArrow: true }), callbacks);

    expect(result).toEqual({ handled: false, completion: null, submit: false });
    expect(callbacks.selectPrevious).not.toHaveBeenCalled();
  });
});

describe("normalizeSlashSubmitText", () => {
  test("keeps plain text unchanged", () => {
    expect(normalizeSlashSubmitText("hello world")).toBe("hello world");
  });

  test("normalizes unique slash prefix to full command", () => {
    expect(normalizeSlashSubmitText("/stat")).toBe("/status");
    expect(normalizeSlashSubmitText("/res")).toBe("/resume");
  });

  test("leaves slash text unchanged when matches are ambiguous or include spaces", () => {
    expect(normalizeSlashSubmitText("/")).toBe("/");
    expect(normalizeSlashSubmitText("/status now")).toBe("/status now");
  });
});
