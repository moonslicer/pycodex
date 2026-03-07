import { formatSlashPopupLine } from "../components/SlashCommandPopup.js";
import type { SlashCommandDef } from "../hooks/useSlashCompletion.js";

const MATCHES: readonly SlashCommandDef[] = [
  { command: "resume", description: "Open session picker" },
  { command: "status", description: "Show session stats" },
];

describe("formatSlashPopupLine", () => {
  test("returns null for empty matches", () => {
    expect(formatSlashPopupLine([], 0)).toBeNull();
  });

  test("renders selected command with selection hint when multiple matches exist", () => {
    expect(formatSlashPopupLine(MATCHES, 1)).toBe(
      "/status  Show session stats [up/down 2/2]",
    );
  });

  test("clamps out-of-bounds selected index", () => {
    expect(formatSlashPopupLine(MATCHES, 99)).toBe(
      "/status  Show session stats [up/down 2/2]",
    );
    expect(formatSlashPopupLine(MATCHES, -1)).toBe(
      "/resume  Open session picker [up/down 1/2]",
    );
  });
});
