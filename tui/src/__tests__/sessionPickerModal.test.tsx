import {
  clampSessionSelection,
  formatSessionRow,
  handleSessionPickerKey,
  truncateForDisplay,
} from "../components/SessionPickerModal.js";
import type { SessionSummaryItem } from "../protocol/types.js";

const SESSION: SessionSummaryItem = {
  thread_id: "thread_1234567890abcdef",
  status: "closed",
  turn_count: 7,
  token_total: 420,
  last_user_message:
    "Hi support team, I reset my password this morning and got locked out.",
  date: "2026-03-06",
};

function makeKey(overrides: {
  downArrow?: boolean;
  upArrow?: boolean;
  return?: boolean;
  escape?: boolean;
} = {}) {
  return {
    downArrow: false,
    upArrow: false,
    return: false,
    escape: false,
    ...overrides,
  };
}

describe("SessionPickerModal helpers", () => {
  test("truncateForDisplay truncates with ellipsis when needed", () => {
    expect(truncateForDisplay("abcdef", 5)).toBe("ab...");
    expect(truncateForDisplay("abc", 5)).toBe("abc");
  });

  test("formatSessionRow includes core summary fields", () => {
    const line = formatSessionRow(SESSION);

    expect(line).toContain("2026-03-06");
    expect(line).toContain("turns:7");
    expect(line).toContain("tokens:420");
    expect(line).toContain("closed");
    expect(line).toContain("thread_12...");
  });

  test("selection index clamps to bounds", () => {
    expect(clampSessionSelection(-1, 3)).toBe(0);
    expect(clampSessionSelection(5, 3)).toBe(2);
    expect(clampSessionSelection(1, 3)).toBe(1);
    expect(clampSessionSelection(2, 0)).toBe(0);
  });

  test("arrow and j/k keys move selection", () => {
    const sessions = [SESSION, { ...SESSION, thread_id: "thread_2" }];

    expect(
      handleSessionPickerKey("", makeKey({ downArrow: true }), 0, sessions),
    ).toEqual({
      action: "down",
      nextIndex: 1,
      selectedThreadId: null,
    });
    expect(handleSessionPickerKey("k", makeKey(), 1, sessions)).toEqual({
      action: "up",
      nextIndex: 0,
      selectedThreadId: null,
    });
  });

  test("enter selects currently highlighted session", () => {
    const sessions = [SESSION, { ...SESSION, thread_id: "thread_2" }];

    expect(
      handleSessionPickerKey("", makeKey({ return: true }), 1, sessions),
    ).toEqual({
      action: "select",
      nextIndex: 1,
      selectedThreadId: "thread_2",
    });
  });

  test("escape dismisses picker", () => {
    const result = handleSessionPickerKey(
      "",
      makeKey({ escape: true }),
      0,
      [SESSION],
    );

    expect(result).toEqual({
      action: "dismiss",
      nextIndex: 0,
      selectedThreadId: null,
    });
  });

  test("enter with empty list is a no-op", () => {
    const result = handleSessionPickerKey("", makeKey({ return: true }), 0, []);

    expect(result).toEqual({
      action: "none",
      nextIndex: 0,
      selectedThreadId: null,
    });
  });
});
