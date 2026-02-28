import { Box, Text } from "ink";

import type { ToolCallState } from "../hooks/useTurns.js";

const MAX_CONTENT_PREVIEW_LINES = 20;

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

type ToolCallPanelProps = {
  toolCall: ToolCallState;
};

export function ToolCallPanel({ toolCall }: ToolCallPanelProps) {
  const contentPreview = previewToolCallContent(toolCall.content);

  return (
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
  );
}
