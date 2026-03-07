import { useCallback, useEffect, useMemo, useState } from "react";

export type SlashCommandDef = {
  command: "resume" | "status" | "new";
  description: string;
};

export const SLASH_COMMANDS: readonly SlashCommandDef[] = [
  { command: "resume", description: "Open session picker" },
  { command: "status", description: "Show session stats" },
  { command: "new", description: "Start a new session" },
];

export function isSlashCompletionOpen(
  value: string,
  dismissedValue: string | null,
  commands: readonly SlashCommandDef[] = SLASH_COMMANDS,
): boolean {
  if (!value.startsWith("/") || value.includes(" ")) {
    return false;
  }

  const query = value.slice(1).toLowerCase();
  const isExactCommand = commands.some((commandDef) => commandDef.command === query);
  if (isExactCommand) {
    return false;
  }

  return dismissedValue !== value;
}

export function getSlashMatches(
  value: string,
  commands: readonly SlashCommandDef[] = SLASH_COMMANDS,
): readonly SlashCommandDef[] {
  if (!value.startsWith("/")) {
    return [];
  }

  const query = value.slice(1).toLowerCase();
  return commands.filter((commandDef) =>
    commandDef.command.startsWith(query),
  );
}

export function clampSlashSelection(
  selectedIndex: number,
  matchesLength: number,
): number {
  if (matchesLength <= 0) {
    return 0;
  }

  return Math.min(Math.max(selectedIndex, 0), matchesLength - 1);
}

export function completeSlashMatch(
  matches: readonly SlashCommandDef[],
  selectedIndex: number,
): string | null {
  const selected = matches[selectedIndex];
  if (selected === undefined) {
    return null;
  }
  return `/${selected.command} `;
}

type SlashCompletionResult = {
  isOpen: boolean;
  matches: readonly SlashCommandDef[];
  selectedIndex: number;
  selectNext: () => void;
  selectPrevious: () => void;
  complete: () => string | null;
  dismiss: () => void;
};

export function useSlashCompletion(value: string): SlashCompletionResult {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [dismissedValue, setDismissedValue] = useState<string | null>(null);
  const matches = useMemo(() => getSlashMatches(value), [value]);
  const isOpen = isSlashCompletionOpen(value, dismissedValue);

  const openMatches = isOpen ? matches : [];
  const clampedIndex = clampSlashSelection(selectedIndex, openMatches.length);

  useEffect(() => {
    if (dismissedValue !== null && dismissedValue !== value) {
      setDismissedValue(null);
    }
  }, [dismissedValue, value]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [openMatches.map((match) => match.command).join(",")]);

  useEffect(() => {
    if (clampedIndex !== selectedIndex) {
      setSelectedIndex(clampedIndex);
    }
  }, [clampedIndex, selectedIndex]);

  const selectNext = useCallback(() => {
    setSelectedIndex((currentIndex) =>
      clampSlashSelection(currentIndex + 1, openMatches.length),
    );
  }, [openMatches.length]);

  const selectPrevious = useCallback(() => {
    setSelectedIndex((currentIndex) =>
      clampSlashSelection(currentIndex - 1, openMatches.length),
    );
  }, [openMatches.length]);

  const complete = useCallback(() => {
    return completeSlashMatch(openMatches, clampedIndex);
  }, [clampedIndex, openMatches]);

  const dismiss = useCallback(() => {
    setDismissedValue(value);
  }, [value]);

  return {
    isOpen,
    matches: openMatches,
    selectedIndex: clampedIndex,
    selectNext,
    selectPrevious,
    complete,
    dismiss,
  };
}
