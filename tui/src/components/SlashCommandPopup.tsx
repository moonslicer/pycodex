import { Box, Text } from "ink";

import type { SlashCommandDef } from "../hooks/useSlashCompletion.js";

type SlashCommandPopupProps = {
  matches: readonly SlashCommandDef[];
  selectedIndex: number;
};

export function SlashCommandPopup({
  matches,
  selectedIndex,
}: SlashCommandPopupProps) {
  if (matches.length === 0) {
    return null;
  }

  return (
    <Box borderStyle="round" flexDirection="column" marginBottom={1} paddingX={1}>
      {matches.map((match, index) => (
        <Text inverse={index === selectedIndex} key={match.command}>
          /{match.command}  {match.description}
        </Text>
      ))}
    </Box>
  );
}
