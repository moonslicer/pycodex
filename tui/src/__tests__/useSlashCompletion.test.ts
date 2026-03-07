import {
  SLASH_COMMANDS,
  clampSlashSelection,
  completeSlashMatch,
  getSlashMatches,
  isSlashCompletionOpen,
} from "../hooks/useSlashCompletion.js";

describe("useSlashCompletion helpers", () => {
  test("slash command catalog includes resume, status, and new", () => {
    expect(SLASH_COMMANDS.map((entry) => entry.command)).toEqual([
      "resume",
      "status",
      "new",
    ]);
  });

  test("isOpen is true for slash prefix without spaces", () => {
    expect(isSlashCompletionOpen("/", null)).toBe(true);
    expect(isSlashCompletionOpen("/r", null)).toBe(true);
  });

  test("isOpen is false when input does not start with slash or has spaces", () => {
    expect(isSlashCompletionOpen("", null)).toBe(false);
    expect(isSlashCompletionOpen("hello", null)).toBe(false);
    expect(isSlashCompletionOpen("/resume now", null)).toBe(false);
  });

  test("dismiss keeps popup closed until value changes", () => {
    expect(isSlashCompletionOpen("/r", "/r")).toBe(false);
    expect(isSlashCompletionOpen("/re", "/r")).toBe(true);
  });

  test("matches include all commands for slash only", () => {
    expect(getSlashMatches("/").map((match) => match.command)).toEqual([
      "resume",
      "status",
      "new",
    ]);
  });

  test("matches filter by prefix", () => {
    expect(getSlashMatches("/r").map((match) => match.command)).toEqual([
      "resume",
    ]);
    expect(getSlashMatches("/st").map((match) => match.command)).toEqual([
      "status",
    ]);
    expect(getSlashMatches("/x")).toEqual([]);
  });

  test("selected index is clamped for negative and overflow values", () => {
    expect(clampSlashSelection(-1, 3)).toBe(0);
    expect(clampSlashSelection(99, 3)).toBe(2);
    expect(clampSlashSelection(2, 3)).toBe(2);
    expect(clampSlashSelection(1, 0)).toBe(0);
  });

  test("complete returns selected command with trailing space", () => {
    const matches = getSlashMatches("/");
    expect(completeSlashMatch(matches, 0)).toBe("/resume ");
    expect(completeSlashMatch(matches, 1)).toBe("/status ");
    expect(completeSlashMatch(matches, 2)).toBe("/new ");
  });

  test("complete returns null for empty matches", () => {
    expect(completeSlashMatch([], 0)).toBeNull();
  });
});
