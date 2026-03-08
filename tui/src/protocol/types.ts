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

export type ContextCompactedEvent = {
  type: "context.compacted";
  thread_id: string;
  turn_id: string;
  strategy: string;
  implementation: string;
  replaced_items: number;
  estimated_prompt_tokens: number;
  context_window_tokens: number;
  remaining_ratio: number;
  threshold_ratio: number;
};

export type ContextPressureEvent = {
  type: "context.pressure";
  thread_id: string;
  turn_id: string;
  remaining_ratio: number;
  context_window_tokens: number;
  estimated_prompt_tokens: number;
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

export type SessionSummaryItem = {
  thread_id: string;
  status: "closed" | "incomplete";
  turn_count: number;
  token_total: number;
  last_user_message: string | null;
  date: string;
  updated_at: string;
  size_bytes: number;
};

export type SessionListedEvent = {
  type: "session.listed";
  sessions: SessionSummaryItem[];
};

export type SessionStatusEvent = {
  type: "session.status";
  thread_id: string;
  turn_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_prompt_tokens: number;
  context_window_tokens: number;
  compaction_count: number;
};

export type HydratedTurnItem = {
  turn_id: string;
  user_text: string;
  assistant_text: string;
  was_compacted?: boolean;
};

export type SessionHydratedEvent = {
  type: "session.hydrated";
  thread_id: string;
  turns: HydratedTurnItem[];
};

export type SlashUnknownEvent = {
  type: "slash.unknown";
  command: string;
};

export type SlashBlockedEvent = {
  type: "slash.blocked";
  command: string;
  reason: "active_turn";
};

export type SessionErrorEvent = {
  type: "session.error";
  operation: "resume" | "new" | "list";
  message: string;
};

export type ProtocolEvent =
  | ThreadStartedEvent
  | TurnStartedEvent
  | ContextCompactedEvent
  | ContextPressureEvent
  | TurnCompletedEvent
  | TurnFailedEvent
  | ItemStartedEvent
  | ItemCompletedEvent
  | ItemUpdatedEvent
  | ApprovalRequestedEvent
  | SessionListedEvent
  | SessionStatusEvent
  | SessionHydratedEvent
  | SlashUnknownEvent
  | SlashBlockedEvent
  | SessionErrorEvent;

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

export type SessionResumeCommand = {
  jsonrpc: "2.0";
  method: "session.resume";
  params: { thread_id: string };
};

export type SessionNewCommand = {
  jsonrpc: "2.0";
  method: "session.new";
  params: Record<string, never>;
};

export type Command =
  | UserInputCommand
  | ApprovalResponseCommand
  | InterruptCommand
  | SessionResumeCommand
  | SessionNewCommand;
