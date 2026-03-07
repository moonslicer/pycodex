import {
  clampSessionSelection,
  formatRelativeTime,
  formatSessionPickerTitle,
  formatSessionRow,
  formatSizeBytes,
  getVisibleSessions,
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
  updated_at: "2026-03-06T00:00:00Z",
  size_bytes: 634_573,
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

  test("formatSessionRow renders prompt preview and metadata line", () => {
    const row = formatSessionRow(
      { ...SESSION, size_bytes: 1536 },
      Date.parse("2026-03-06T02:00:00Z"),
    );

    expect(row.primary).toContain("Hi support team");
    expect(row.secondary).toBe("2h ago · 1.5KB");
  });

  test("formatSessionRow falls back when last message is empty", () => {
    const row = formatSessionRow(
      { ...SESSION, last_user_message: "   " },
      Date.parse("2026-03-06T00:00:00Z"),
    );
    expect(row.primary).toBe("No prompt yet");
  });

  test("formatRelativeTime handles invalid timestamps", () => {
    expect(formatRelativeTime("not-a-date")).toBe("unknown time");
  });

  test("formatSizeBytes humanizes common ranges", () => {
    expect(formatSizeBytes(42)).toBe("42B");
    expect(formatSizeBytes(1024)).toBe("1KB");
    expect(formatSizeBytes(1536)).toBe("1.5KB");
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

  test("getVisibleSessions caps window and follows selected index", () => {
    const sessions: SessionSummaryItem[] = Array.from({ length: 8 }, (_, idx) => ({
      ...SESSION,
      thread_id: `thread_${String(idx)}`,
    }));

    expect(getVisibleSessions(sessions, 0, 5).map((entry) => entry.originalIndex)).toEqual([
      0,
      1,
      2,
      3,
      4,
    ]);
    expect(getVisibleSessions(sessions, 4, 5).map((entry) => entry.originalIndex)).toEqual([
      2,
      3,
      4,
      5,
      6,
    ]);
    expect(getVisibleSessions(sessions, 7, 5).map((entry) => entry.originalIndex)).toEqual([
      3,
      4,
      5,
      6,
      7,
    ]);
  });

  test("getVisibleSessions returns all sessions when list is smaller than window", () => {
    const sessions: SessionSummaryItem[] = [
      { ...SESSION, thread_id: "thread_1" },
      { ...SESSION, thread_id: "thread_2" },
      { ...SESSION, thread_id: "thread_3" },
    ];

    expect(getVisibleSessions(sessions, 1, 5).map((entry) => entry.originalIndex)).toEqual([
      0,
      1,
      2,
    ]);
  });

  test("formatSessionPickerTitle includes selected position when sessions exist", () => {
    expect(formatSessionPickerTitle(8, 0)).toBe("Resume Session (1 of 8)");
    expect(formatSessionPickerTitle(8, 4)).toBe("Resume Session (5 of 8)");
    expect(formatSessionPickerTitle(8, 99)).toBe("Resume Session (8 of 8)");
  });

  test("formatSessionPickerTitle falls back to base title for empty list", () => {
    expect(formatSessionPickerTitle(0, 0)).toBe("Resume Session");
  });
});
