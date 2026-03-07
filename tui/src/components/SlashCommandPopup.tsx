import { Box, Text } from "ink";

import type { SlashCommandDef } from "../hooks/useSlashCompletion.js";

type SlashCommandPopupProps = {
  matches: readonly SlashCommandDef[];
  selectedIndex: number;
};

export const MAX_VISIBLE_SLASH_COMMANDS = 5;

export type VisibleSlashMatch = {
  match: SlashCommandDef;
  originalIndex: number;
};

export function getVisibleSlashMatches(
  matches: readonly SlashCommandDef[],
  selectedIndex: number,
  maxVisible: number = MAX_VISIBLE_SLASH_COMMANDS,
): readonly VisibleSlashMatch[] {
  if (matches.length === 0 || maxVisible <= 0) {
    return [];
  }

  const normalizedIndex = Math.min(Math.max(selectedIndex, 0), matches.length - 1);
  const windowSize = Math.min(matches.length, maxVisible);

  const centeredStart = normalizedIndex - Math.floor(windowSize / 2);
  const maxStart = Math.max(0, matches.length - windowSize);
  const start = Math.min(Math.max(centeredStart, 0), maxStart);
  const end = start + windowSize;

  const visible: VisibleSlashMatch[] = [];
  for (let index = start; index < end; index += 1) {
    const match = matches[index];
    if (match !== undefined) {
      visible.push({ match, originalIndex: index });
    }
  }
  return visible;
}

export function formatSlashFooter(
  matches: readonly SlashCommandDef[],
  selectedIndex: number,
): string | null {
  if (matches.length === 0) {
    return null;
  }

  const normalizedIndex = Math.min(Math.max(selectedIndex, 0), matches.length - 1);
  return matches.length > 1
    ? `[up/down ${String(normalizedIndex + 1)}/${String(matches.length)}] [tab] complete [enter] submit`
    : "[tab] complete [enter] submit";
}

export function SlashCommandPopup({
  matches,
  selectedIndex,
}: SlashCommandPopupProps) {
  const visibleMatches = getVisibleSlashMatches(matches, selectedIndex);
  const footer = formatSlashFooter(matches, selectedIndex);
  if (visibleMatches.length === 0 || footer === null) {
    return null;
  }

  return (
    <Box borderStyle="round" flexDirection="column" paddingX={1}>
      {visibleMatches.map(({ match, originalIndex }) => (
        <Text inverse={originalIndex === selectedIndex} key={match.command}>
          /{match.command}  {match.description}
        </Text>
      ))}
      <Text dimColor>{footer}</Text>
    </Box>
  );
}
