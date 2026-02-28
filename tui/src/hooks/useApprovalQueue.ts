import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import type { ProtocolEvent, ApprovalDecision } from "../protocol/types.js";
import type { ProtocolWriter } from "../protocol/writer.js";

export type ApprovalRequest = {
  thread_id: string;
  turn_id: string;
  request_id: string;
  tool: string;
  preview: string;
};

export type ApprovalQueueState = {
  queue: ApprovalRequest[];
};

export type ApprovalDecisionLog = {
  request_id: string;
  turn_id: string;
  tool: string;
  preview: string;
  decision: ApprovalDecision;
  source: "fresh_prompt";
};

export const INITIAL_APPROVAL_QUEUE_STATE: ApprovalQueueState = {
  queue: [],
};

// Maximum number of pending approval requests held in the TS queue.
// Requests beyond this limit are dropped with a warning.
const MAX_APPROVAL_QUEUE_SIZE = 100;

type ApprovalEnqueueDecision = "enqueue" | "duplicate" | "overflow";

type ApprovalQueueAction =
  | {
      type: "event";
      event: ProtocolEvent;
    }
  | {
      type: "dequeue";
      request_id: string;
    }
  | {
      type: "reset";
    };

export function reduceApprovalQueue(
  state: ApprovalQueueState,
  event: ProtocolEvent,
): ApprovalQueueState {
  // Terminal turn events flush all queued requests for that turn so a crashed
  // or interrupted turn can never leave the modal/input permanently blocked.
  if (event.type === "turn.completed" || event.type === "turn.failed") {
    const next = state.queue.filter((r) => r.turn_id !== event.turn_id);
    if (next.length === state.queue.length) {
      return state;
    }
    return { ...state, queue: next };
  }

  if (event.type !== "approval.request") {
    return state;
  }

  const decision = classifyApprovalRequest(state, event);
  if (decision !== "enqueue") {
    return state;
  }

  return {
    ...state,
    queue: [
      ...state.queue,
      {
        thread_id: event.thread_id,
        turn_id: event.turn_id,
        request_id: event.request_id,
        tool: event.tool,
        preview: event.preview,
      },
    ],
  };
}

export function classifyApprovalRequest(
  state: ApprovalQueueState,
  event: {
    request_id: string;
  },
): ApprovalEnqueueDecision {
  if (state.queue.some((request) => request.request_id === event.request_id)) {
    return "duplicate";
  }
  if (state.queue.length >= MAX_APPROVAL_QUEUE_SIZE) {
    return "overflow";
  }
  return "enqueue";
}

export function maybeAutoDenyOverflowedApprovalRequest(
  writer: Pick<ProtocolWriter, "sendApprovalResponse">,
  state: ApprovalQueueState,
  event: {
    request_id: string;
  },
): boolean {
  if (classifyApprovalRequest(state, event) !== "overflow") {
    return false;
  }
  writer.sendApprovalResponse(event.request_id, "denied");
  return true;
}

export function approvalQueueReducer(
  state: ApprovalQueueState,
  action: ApprovalQueueAction,
): ApprovalQueueState {
  if (action.type === "reset") {
    return INITIAL_APPROVAL_QUEUE_STATE;
  }

  if (action.type === "dequeue") {
    if (state.queue.length === 0) {
      return state;
    }

    const [head, ...rest] = state.queue;
    if (head === undefined || head.request_id !== action.request_id) {
      return state;
    }

    return {
      ...state,
      queue: rest,
    };
  }

  return reduceApprovalQueue(state, action.event);
}

export type ApprovalQueueDispatch = {
  currentRequest: ApprovalRequest | null;
  decisionLog: readonly ApprovalDecisionLog[];
  queueLength: number;
  respond: (decision: ApprovalDecision) => void;
};

export function sendApprovalResponseForRequest(
  writer: Pick<ProtocolWriter, "sendApprovalResponse">,
  request: ApprovalRequest | null,
  decision: ApprovalDecision,
): string | null {
  if (request === null) {
    return null;
  }

  writer.sendApprovalResponse(request.request_id, decision);
  return request.request_id;
}

/**
 * Processes approval request events from the shared protocol event array.
 *
 * CONTRACT: `events` must be the stable array reference managed by
 * `useProtocolEvents` (via React useState). The hook tracks how many events
 * it has processed via `processedEventCount` and only iterates new entries on
 * each render. If the caller ever recreates the array (e.g. wraps in useMemo),
 * the ref-based counter will trigger a full reset on apparent shrinkage.
 */
export function useApprovalQueue(
  events: readonly ProtocolEvent[],
  writer: ProtocolWriter,
): ApprovalQueueState & ApprovalQueueDispatch {
  const [state, dispatch] = useReducer(
    approvalQueueReducer,
    INITIAL_APPROVAL_QUEUE_STATE,
  );
  const processedEventCount = useRef(0);
  const [decisionLog, setDecisionLog] = useState<ApprovalDecisionLog[]>([]);

  const currentRequest = state.queue[0] ?? null;

  useEffect(() => {
    let nextState = state;

    if (events.length < processedEventCount.current) {
      dispatch({ type: "reset" });
      setDecisionLog([]);
      processedEventCount.current = 0;
      nextState = INITIAL_APPROVAL_QUEUE_STATE;
    }

    for (
      let index = processedEventCount.current;
      index < events.length;
      index += 1
    ) {
      const event = events[index];
      if (event === undefined) {
        continue;
      }

      if (event.type === "approval.request") {
        if (classifyApprovalRequest(nextState, event) === "duplicate") {
          continue;
        }
        try {
          const didAutoDeny = maybeAutoDenyOverflowedApprovalRequest(
            writer,
            nextState,
            event,
          );
          if (didAutoDeny) {
            continue;
          }
        } catch (err) {
          try {
            process.stderr.write(
              `[tui] auto-deny failed for overflowed approval ${event.request_id}: ${String(err)}\n`,
            );
          } catch {
            // Keep processing even if stderr itself is unavailable.
          }
        }
      }

      nextState = reduceApprovalQueue(nextState, event);

      dispatch({
        type: "event",
        event,
      });
    }

    processedEventCount.current = events.length;
  }, [events, state, writer]);

  const respond = useCallback(
    (decision: ApprovalDecision): void => {
      let requestId: string | null;
      try {
        requestId = sendApprovalResponseForRequest(
          writer,
          currentRequest,
          decision,
        );
      } catch (err) {
        process.stderr.write(
          `[tui] approval response failed: ${String(err)}\n`,
        );
        return;
      }
      if (requestId === null) {
        return;
      }

      dispatch({
        type: "dequeue",
        request_id: requestId,
      });
      if (currentRequest !== null) {
        setDecisionLog((current) => {
          const next = [
            ...current,
            {
              request_id: currentRequest.request_id,
              turn_id: currentRequest.turn_id,
              tool: currentRequest.tool,
              preview: currentRequest.preview,
              decision,
              source: "fresh_prompt" as const,
            },
          ];
          return next.length > 500 ? next.slice(-500) : next;
        });
      }
    },
    [currentRequest, writer],
  );

  return {
    ...state,
    currentRequest,
    decisionLog,
    queueLength: state.queue.length,
    respond,
  };
}
