import { Text } from "ink";

import type { ContextCompactedEvent, TokenUsage } from "../protocol/types.js";

type StatusBarProps = {
  cumulativeUsage: TokenUsage | null;
  compactionDetail: ContextCompactedEvent | null;
  compactionStatus: "pending" | "triggered" | "idle";
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

function toPercentage(value: number): string {
  return `${(Math.round(value * 1000) / 10).toFixed(1)}%`;
}

export function formatCompactionSummary(
  status: "pending" | "triggered" | "idle",
  detail: ContextCompactedEvent | null,
): string {
  if (status === "pending") {
    return "compaction: pending";
  }
  if (detail !== null) {
    const contextFillRatio =
      detail.context_window_tokens <= 0
        ? 0
        : detail.estimated_prompt_tokens / detail.context_window_tokens;
    const thresholdFillRatio = 1 - detail.threshold_ratio;
    const replaced = String(detail.replaced_items);
    return `compaction: ${status} (replaced ${replaced}; context ${toPercentage(contextFillRatio)} / threshold ${toPercentage(thresholdFillRatio)})`;
  }
  return `compaction: ${status}`;
}

export function StatusBar({
  cumulativeUsage,
  compactionDetail,
  compactionStatus,
  isBusy,
  latestUsage,
  threadId,
  turnCount,
}: StatusBarProps) {
  const statusLabel = isBusy ? "busy" : "idle";
  const threadLabel = threadId ?? "pending";
  const turnCountLabel = String(turnCount);
  const usageLabel = formatUsageSummary(latestUsage, cumulativeUsage);
  const compactionLabel = formatCompactionSummary(compactionStatus, compactionDetail);

  return <Text dimColor>{`thread: ${threadLabel} | turns: ${turnCountLabel} | status: ${statusLabel} | ${usageLabel} | ${compactionLabel}`}</Text>;
}
