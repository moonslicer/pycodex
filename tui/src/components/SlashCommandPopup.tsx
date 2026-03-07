import { Box, Text } from "ink";

import type { SlashCommandDef } from "../hooks/useSlashCompletion.js";

type SlashCommandPopupProps = {
  matches: readonly SlashCommandDef[];
  selectedIndex: number;
};

export function formatSlashPopupLine(
  matches: readonly SlashCommandDef[],
  selectedIndex: number,
): string | null {
  if (matches.length === 0) {
    return null;
  }

  const normalizedIndex = Math.min(
    Math.max(selectedIndex, 0),
    matches.length - 1,
  );
  const selected = matches[normalizedIndex];
  if (selected === undefined) {
    return null;
  }

  const selectionHint = matches.length > 1
    ? ` [up/down ${String(normalizedIndex + 1)}/${String(matches.length)}]`
    : "";
  return `/${selected.command}  ${selected.description}${selectionHint}`;
}

export function SlashCommandPopup({
  matches,
  selectedIndex,
}: SlashCommandPopupProps) {
  const line = formatSlashPopupLine(matches, selectedIndex);
  if (line === null) {
    return null;
  }

  return (
    <Box>
      <Text dimColor>{line}</Text>
    </Box>
  );
}
