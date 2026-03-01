import { Box, Text } from "ink";

import type { ToolCallState } from "../hooks/useTurns.js";

const MAX_CONTENT_PREVIEW_LINES = 20;
const MAX_COMMAND_PREVIEW_CHARS = 80;

export function statusLabelForToolCall(status: ToolCallState["status"]): string {
  switch (status) {
    case "pending":
      return "pending";
    case "error":
      return "error";
    case "done":
      return "done";
  }
}

export function previewToolCallContent(
  content: string | null,
  maxLines?: number,
): {
  lines: string[];
  truncated: boolean;
} {
  if (content === null || content.length === 0) {
    return { lines: [], truncated: false };
  }

  const limit = maxLines ?? MAX_CONTENT_PREVIEW_LINES;
  const splitLines = content.split("\n");
  return {
    lines: splitLines.slice(0, limit),
    truncated: splitLines.length > limit,
  };
}

function parseToolArguments(
  argumentsText: string | null,
): Record<string, unknown> | null {
  if (argumentsText === null || argumentsText.length === 0) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(argumentsText);
    if (typeof parsed !== "object" || parsed === null) {
      return null;
    }
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

function truncateText(value: string, maxChars: number): string {
  if (value.length <= maxChars) {
    return value;
  }
  return `${value.slice(0, maxChars - 1)}…`;
}

export function summarizeToolCall(toolCall: ToolCallState): string {
  const parsedArgs = parseToolArguments(toolCall.arguments);
  if (toolCall.name === "read_file") {
    return "Read 1 file";
  }
  if (toolCall.name === "list_dir") {
    return "Listed directory";
  }
  if (toolCall.name === "write_file") {
    return "Wrote file";
  }
  if (toolCall.name === "shell") {
    const commandRaw = parsedArgs?.command;
    if (typeof commandRaw === "string" && commandRaw.length > 0) {
      return `Ran shell: ${truncateText(commandRaw, MAX_COMMAND_PREVIEW_CHARS)}`;
    }
    return "Ran shell command";
  }
  return `Called ${toolCall.name}`;
}

export function statusDotColorForToolCall(status: ToolCallState["status"]): string {
  switch (status) {
    case "pending":
      return "yellow";
    case "error":
      return "red";
    case "done":
      return "green";
  }
}

type ToolCallPanelProps = {
  showDetails?: boolean;
  toolCall: ToolCallState;
};

export function ToolCallPanel({ showDetails = false, toolCall }: ToolCallPanelProps) {
  const contentPreview = previewToolCallContent(toolCall.content);
  const hasDetails = (
    (toolCall.arguments !== null && toolCall.arguments.length > 0) ||
    contentPreview.lines.length > 0 ||
    contentPreview.truncated
  );
  const hint = !showDetails && hasDetails ? " (ctrl+o to expand)" : "";

  return (
    <Box flexDirection="column" marginLeft={2}>
      <Text color={statusDotColorForToolCall(toolCall.status)}>
        {`● ${summarizeToolCall(toolCall)}${hint}`}
      </Text>
      {showDetails ? (
        <Box
          borderStyle="single"
          flexDirection="column"
          marginLeft={2}
          paddingX={1}
        >
          <Text color="blue">{`tool: ${toolCall.name} (${statusLabelForToolCall(toolCall.status)})`}</Text>
          {toolCall.arguments !== null && toolCall.arguments.length > 0 ? (
            <Text dimColor>{`args: ${toolCall.arguments}`}</Text>
          ) : null}
          {contentPreview.lines.map((line, index) => (
            <Text dimColor key={`${toolCall.item_id}:line:${String(index)}`}>
              {line}
            </Text>
          ))}
          {contentPreview.truncated ? <Text dimColor>(output truncated)</Text> : null}
        </Box>
      ) : null}
    </Box>
  );
}
