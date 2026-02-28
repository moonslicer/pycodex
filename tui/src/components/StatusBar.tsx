import { Text } from "ink";

import type { TokenUsage } from "../protocol/types.js";

type StatusBarProps = {
  cumulativeUsage: TokenUsage | null;
  isBusy: boolean;
  latestUsage: TokenUsage | null;
  threadId: string | null;
  turnCount: number;
};

function formatUsageValue(usage: TokenUsage): string {
  return `${String(usage.input_tokens)}/${String(usage.output_tokens)}`;
}

export function formatUsageSummary(
  latestUsage: TokenUsage | null,
  cumulativeUsage: TokenUsage | null,
): string {
  if (latestUsage !== null && cumulativeUsage !== null) {
    return `usage latest(in/out): ${formatUsageValue(latestUsage)} | total(in/out): ${formatUsageValue(cumulativeUsage)}`;
  }
  if (latestUsage !== null) {
    return `usage latest(in/out): ${formatUsageValue(latestUsage)}`;
  }
  if (cumulativeUsage !== null) {
    return `usage total(in/out): ${formatUsageValue(cumulativeUsage)}`;
  }
  return "usage: n/a";
}

export function StatusBar({
  cumulativeUsage,
  isBusy,
  latestUsage,
  threadId,
  turnCount,
}: StatusBarProps) {
  const statusLabel = isBusy ? "busy" : "idle";
  const threadLabel = threadId ?? "pending";
  const turnCountLabel = String(turnCount);
  const usageLabel = formatUsageSummary(latestUsage, cumulativeUsage);

  return (
    <Text dimColor>{`thread: ${threadLabel} | turns: ${turnCountLabel} | status: ${statusLabel} | ${usageLabel}`}</Text>
  );
}
