export type TokenUsage = {
  input_tokens: number;
  output_tokens: number;
};

export type UsageSnapshot = {
  turn: TokenUsage;
  cumulative: TokenUsage;
};

export type ThreadStartedEvent = {
  type: "thread.started";
  thread_id: string;
};

export type TurnStartedEvent = {
  type: "turn.started";
  thread_id: string;
  turn_id: string;
};

export type TurnCompletedEvent = {
  type: "turn.completed";
  thread_id: string;
  turn_id: string;
  final_text: string;
  usage: UsageSnapshot | null;
};

export type TurnFailedEvent = {
  type: "turn.failed";
  thread_id: string;
  turn_id: string;
  error: string;
};

export type ItemStartedEvent = {
  type: "item.started";
  thread_id: string;
  turn_id: string;
  item_id: string;
  item_kind: "tool_call" | "assistant_message";
  name?: string | null;
  arguments?: string | null;
};

export type ItemCompletedEvent = {
  type: "item.completed";
  thread_id: string;
  turn_id: string;
  item_id: string;
  item_kind: "tool_result" | "assistant_message";
  content: string;
};

export type ItemUpdatedEvent = {
  type: "item.updated";
  thread_id: string;
  turn_id: string;
  item_id: string;
  delta: string;
};

export type ApprovalRequestedEvent = {
  type: "approval.request";
  thread_id: string;
  turn_id: string;
  request_id: string;
  tool: string;
  preview: string;
};

export type ProtocolEvent =
  | ThreadStartedEvent
  | TurnStartedEvent
  | TurnCompletedEvent
  | TurnFailedEvent
  | ItemStartedEvent
  | ItemCompletedEvent
  | ItemUpdatedEvent
  | ApprovalRequestedEvent;

export type ApprovalDecision =
  | "approved"
  | "denied"
  | "approved_for_session"
  | "abort";

export type UserInputCommand = {
  jsonrpc: "2.0";
  method: "user.input";
  params: { text: string };
};

export type ApprovalResponseCommand = {
  jsonrpc: "2.0";
  method: "approval.response";
  params: { request_id: string; decision: ApprovalDecision };
};

export type InterruptCommand = {
  jsonrpc: "2.0";
  method: "interrupt";
  params: Record<string, never>;
};

export type Command =
  | UserInputCommand
  | ApprovalResponseCommand
  | InterruptCommand;
