import { Box, Text, useInput } from "ink";

import type { ApprovalDecision } from "../protocol/types.js";
import type { ApprovalRequest } from "../hooks/useApprovalQueue.js";

type ApprovalModalProps = {
  request: ApprovalRequest;
  onRespond: (decision: ApprovalDecision) => void;
};

export function decisionForApprovalKey(input: string): ApprovalDecision | null {
  const normalized = input.toLowerCase();
  if (normalized === "y") {
    return "approved";
  }
  if (normalized === "n") {
    return "denied";
  }
  if (normalized === "s") {
    return "approved_for_session";
  }
  if (normalized === "a") {
    return "abort";
  }
  return null;
}

export function ApprovalModal({ request, onRespond }: ApprovalModalProps) {
  useInput((input) => {
    const decision = decisionForApprovalKey(input);
    if (decision !== null) {
      onRespond(decision);
    }
  });

  return (
    <Box
      borderStyle="double"
      borderColor="yellow"
      flexDirection="column"
      paddingX={1}
      marginTop={1}
    >
      <Text color="yellow">Approval required</Text>
      <Text>{`Tool: ${request.tool}`}</Text>
      <Text>{`Preview: ${request.preview}`}</Text>
      <Text dimColor>[y] approve [n] deny [s] session [a] abort</Text>
    </Box>
  );
}
