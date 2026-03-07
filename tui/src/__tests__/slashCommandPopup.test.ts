import {
  formatSlashFooter,
  getVisibleSlashMatches,
} from "../components/SlashCommandPopup.js";
import type { SlashCommandDef } from "../hooks/useSlashCompletion.js";

const MATCHES: readonly SlashCommandDef[] = [
  { command: "resume", description: "Open session picker" },
  { command: "status", description: "Show session stats" },
  { command: "new", description: "Start a new session" },
];

describe("getVisibleSlashMatches", () => {
  test("returns empty for empty matches", () => {
    expect(getVisibleSlashMatches([], 0)).toEqual([]);
  });

  test("returns all matches when match count is below window", () => {
    expect(getVisibleSlashMatches(MATCHES, 1, 5)).toEqual([
      { match: MATCHES[0], originalIndex: 0 },
      { match: MATCHES[1], originalIndex: 1 },
      { match: MATCHES[2], originalIndex: 2 },
    ]);
  });

  test("centers selected row when windowing", () => {
    const many: SlashCommandDef[] = [
      { command: "resume", description: "a" },
      { command: "status", description: "b" },
      { command: "new", description: "c" },
      { command: "resume", description: "d" },
      { command: "status", description: "e" },
      { command: "new", description: "f" },
    ];
    expect(getVisibleSlashMatches(many, 4, 3)).toEqual([
      { match: many[3], originalIndex: 3 },
      { match: many[4], originalIndex: 4 },
      { match: many[5], originalIndex: 5 },
    ]);
  });
});

describe("formatSlashFooter", () => {
  test("returns null for empty matches", () => {
    expect(formatSlashFooter([], 0)).toBeNull();
  });

  test("renders selection hint for multiple matches", () => {
    expect(formatSlashFooter(MATCHES, 1)).toBe(
      "[up/down 2/3] [tab] complete [enter] submit",
    );
  });

  test("clamps out-of-bounds index in footer", () => {
    expect(formatSlashFooter(MATCHES, 99)).toBe(
      "[up/down 3/3] [tab] complete [enter] submit",
    );
  });
});
