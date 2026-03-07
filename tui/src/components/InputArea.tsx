import { useEffect, useRef, useState } from "react";
import { Box, Text, useInput } from "ink";

import { useSlashCompletion } from "../hooks/useSlashCompletion.js";
import { SlashCommandPopup } from "./SlashCommandPopup.js";

type InputAreaProps = {
  disabled: boolean;
  hasActiveTurn: boolean;
  onExit: () => void;
  onInterrupt: () => void;
  onSubmit: (text: string) => void;
};

const BRACKETED_PASTE_START = "\u001b[200~";
const BRACKETED_PASTE_END = "\u001b[201~";

type EditorState = {
  value: string;
  cursorIndex: number;
  history: readonly string[];
  historyIndex: number | null;
  draftBeforeHistory: string;
};

export const HISTORY_MAX = 100;

export const INITIAL_EDITOR_STATE: EditorState = {
  value: "",
  cursorIndex: 0,
  history: [],
  historyIndex: null,
  draftBeforeHistory: "",
};

export function handleCtrlC(hasActiveTurn: boolean, callbacks: {
  onClearInput: () => void;
  onInterrupt: () => void;
}): void {
  callbacks.onClearInput();
  if (hasActiveTurn) {
    callbacks.onInterrupt();
  }
}

export function handleCtrlX(callbacks: {
  onExit: () => void;
}): void {
  callbacks.onExit();
}

export function sanitizeInputChunk(input: string): string {
  const withoutPasteMarkers = input
    .replaceAll(BRACKETED_PASTE_START, "")
    .replaceAll(BRACKETED_PASTE_END, "")
    .replace(/[\r\n]+/g, "");

  let sanitized = "";
  for (const char of withoutPasteMarkers) {
    const codepoint = char.codePointAt(0);
    if (codepoint === undefined) {
      continue;
    }
    if (codepoint <= 0x1f || codepoint === 0x7f) {
      continue;
    }
    sanitized += char;
  }

  return sanitized;
}

export function isSubmitInput(input: string, keyReturn: boolean): boolean {
  if (keyReturn) {
    return true;
  }

  const withoutPasteMarkers = input
    .replaceAll(BRACKETED_PASTE_START, "")
    .replaceAll(BRACKETED_PASTE_END, "");
  if (!/[\r\n]/.test(withoutPasteMarkers)) {
    return false;
  }
  return withoutPasteMarkers.replace(/[\r\n]/g, "").length === 0;
}

// Known limitations:
// - Cursor movement uses UTF-16 code units and can split surrogate pairs.
// - History is process-local and not persisted.
// - Ctrl+Left/Ctrl+Right word-jump is intentionally unsupported.
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

export function deleteBackward(
  value: string,
  cursor: number,
): { value: string; cursorIndex: number } {
  if (cursor === 0) {
    return { value, cursorIndex: 0 };
  }
  return {
    value: value.slice(0, cursor - 1) + value.slice(cursor),
    cursorIndex: cursor - 1,
  };
}

export function deleteForward(
  value: string,
  cursor: number,
): { value: string; cursorIndex: number } {
  if (cursor >= value.length) {
    return { value, cursorIndex: cursor };
  }
  return {
    value: value.slice(0, cursor) + value.slice(cursor + 1),
    cursorIndex: cursor,
  };
}

export function moveCursorLeft(cursor: number): number {
  return Math.max(0, cursor - 1);
}

export function moveCursorRight(cursor: number, valueLength: number): number {
  return Math.min(valueLength, cursor + 1);
}

export function recallHistoryUp(state: EditorState): EditorState {
  const { history, historyIndex, value } = state;
  if (history.length === 0) {
    return state;
  }

  if (historyIndex === null) {
    const newIndex = history.length - 1;
    const entry = history[newIndex];
    if (entry === undefined) {
      return state;
    }
    return {
      ...state,
      draftBeforeHistory: value,
      historyIndex: newIndex,
      value: entry,
      cursorIndex: entry.length,
    };
  }

  if (historyIndex === 0) {
    return state;
  }

  const newIndex = historyIndex - 1;
  const entry = history[newIndex];
  if (entry === undefined) {
    return state;
  }
  return {
    ...state,
    historyIndex: newIndex,
    value: entry,
    cursorIndex: entry.length,
  };
}

export function recallHistoryDown(state: EditorState): EditorState {
  const { history, historyIndex, draftBeforeHistory } = state;
  if (historyIndex === null) {
    return state;
  }

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
  if (entry === undefined) {
    return state;
  }
  return {
    ...state,
    historyIndex: newIndex,
    value: entry,
    cursorIndex: entry.length,
  };
}

export function pushHistoryEntry(
  history: readonly string[],
  text: string,
  maxEntries: number,
): readonly string[] {
  const next = [...history, text];
  return next.length > maxEntries ? next.slice(next.length - maxEntries) : next;
}

export function resetEditorForDisabled(state: EditorState): EditorState {
  return {
    ...INITIAL_EDITOR_STATE,
    history: state.history,
  };
}

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

type PopupKey = MinimalKey & {
  tab?: boolean;
  escape?: boolean;
};

type PopupCallbacks = {
  complete: () => string | null;
  dismiss: () => void;
  selectNext: () => void;
  selectPrevious: () => void;
};

export function handleSlashPopupKey(
  isOpen: boolean,
  key: PopupKey,
  callbacks: PopupCallbacks,
): {
  handled: boolean;
  completion: string | null;
} {
  if (!isOpen || key.ctrl || key.meta) {
    return {
      handled: false,
      completion: null,
    };
  }

  if (key.upArrow) {
    callbacks.selectPrevious();
    return {
      handled: true,
      completion: null,
    };
  }
  if (key.downArrow) {
    callbacks.selectNext();
    return {
      handled: true,
      completion: null,
    };
  }
  if (key.escape ?? false) {
    callbacks.dismiss();
    return {
      handled: true,
      completion: null,
    };
  }
  if (key.return || (key.tab ?? false)) {
    const completion = callbacks.complete();
    if (completion === null) {
      return {
        handled: false,
        completion: null,
      };
    }
    return {
      handled: true,
      completion,
    };
  }

  return {
    handled: false,
    completion: null,
  };
}

export function computeKeyEvent(
  state: EditorState,
  input: string,
  key: MinimalKey,
  disabled: boolean,
): KeyEventResult {
  if (disabled) {
    return { type: "noop" };
  }

  if (isSubmitInput(input, key.return)) {
    const text = state.value.trim();
    if (text.length === 0) {
      return { type: "noop" };
    }
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
    // Many terminals report the Backspace/Delete key as `delete`.
    // Treat it as backward delete to match expected shell editing.
    const deletion = deleteBackward(state.value, state.cursorIndex);
    return {
      type: "state",
      state: {
        ...state,
        ...deletion,
        historyIndex: null,
        draftBeforeHistory: "",
      },
    };
  }

  if (key.ctrl || key.meta || input.length === 0) {
    return { type: "noop" };
  }

  const sanitized = sanitizeInputChunk(input);
  if (sanitized.length === 0) {
    return { type: "noop" };
  }

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

export function InputArea({
  disabled,
  hasActiveTurn,
  onExit,
  onInterrupt,
  onSubmit,
}: InputAreaProps) {
  const [editorState, setEditorStateValue] = useState<EditorState>(
    INITIAL_EDITOR_STATE,
  );
  const editorStateRef = useRef<EditorState>(INITIAL_EDITOR_STATE);
  const slashCompletion = useSlashCompletion(editorState.value);

  const setEditorState = (next: EditorState): void => {
    editorStateRef.current = next;
    setEditorStateValue(next);
  };

  useEffect(() => {
    if (disabled) {
      setEditorState(resetEditorForDisabled(editorStateRef.current));
    }
  }, [disabled]);

  useInput((input, key) => {
    if (key.ctrl && input.toLowerCase() === "c") {
      handleCtrlC(hasActiveTurn, {
        onClearInput: () => {
          setEditorState(resetEditorForDisabled(editorStateRef.current));
        },
        onInterrupt,
      });
      return;
    }

    if (key.ctrl && input.toLowerCase() === "x") {
      handleCtrlX({ onExit });
      return;
    }

    const popupResult = handleSlashPopupKey(
      slashCompletion.isOpen,
      key,
      {
        complete: slashCompletion.complete,
        dismiss: slashCompletion.dismiss,
        selectNext: slashCompletion.selectNext,
        selectPrevious: slashCompletion.selectPrevious,
      },
    );
    if (popupResult.handled) {
      if (popupResult.completion !== null) {
        setEditorState({
          ...editorStateRef.current,
          value: popupResult.completion,
          cursorIndex: popupResult.completion.length,
          historyIndex: null,
          draftBeforeHistory: "",
        });
      }
      return;
    }

    const result = computeKeyEvent(editorStateRef.current, input, key, disabled);
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

  const before = `> ${editorState.value.slice(0, editorState.cursorIndex)}`;
  const atCursor = editorState.value[editorState.cursorIndex] ?? " ";
  const after = editorState.value.slice(editorState.cursorIndex + 1);

  return (
    <Box flexDirection="column">
      {slashCompletion.isOpen && slashCompletion.matches.length > 0 ? (
        <SlashCommandPopup
          matches={slashCompletion.matches}
          selectedIndex={slashCompletion.selectedIndex}
        />
      ) : null}
      <Box borderStyle="single" paddingX={1}>
        {disabled ? (
          <Text color="yellow">
            Input disabled while a turn is active or approval is pending
          </Text>
        ) : (
          <>
            <Text>{before}</Text>
            <Text inverse>{atCursor}</Text>
            {after.length > 0 ? <Text>{after}</Text> : null}
          </>
        )}
      </Box>
    </Box>
  );
}
