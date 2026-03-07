import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import type {
  ContextCompactedEvent,
  ProtocolEvent,
  UsageSnapshot,
} from "../protocol/types.js";
import { sliceUnprocessedEvents } from "./eventCursor.js";
import {
  INITIAL_LINE_BUFFER_STATE,
  reduceLineBuffer,
} from "./useLineBuffer.js";

export type ToolCallState = {
  item_id: string;
  name: string;
  arguments: string | null;
  status: "pending" | "done" | "error";
  content: string | null;
};

export type TurnState = {
  turn_id: string;
  userText: string;
  assistantLines: string[];
  partialLine: string;
  toolCalls: Record<string, ToolCallState>;
  status: "active" | "completed" | "failed";
  error: string | null;
  usage: UsageSnapshot | null;
  compaction: {
    status: "pending" | "triggered" | "idle";
    detail: ContextCompactedEvent | null;
  };
};

export type TurnsViewState = {
  threadId: string | null;
  turns: TurnState[];
};

export const INITIAL_TURNS_STATE: TurnsViewState = {
  threadId: null,
  turns: [],
};

type TurnsAction =
  | {
      type: "event";
      event: ProtocolEvent;
    }
  | {
      type: "item.updated.batch";
      updates: BufferedItemUpdate[];
    }
  | {
      type: "user.input";
      turn_id: string;
      text: string;
    }
  | {
      type: "reset";
    };

function updateTurn(
  turns: TurnState[],
  turnId: string,
  update: (turn: TurnState) => TurnState,
): TurnState[] {
  const index = turns.findIndex((turn) => turn.turn_id === turnId);
  if (index === -1) {
    return turns;
  }

  const nextTurns = [...turns];
  const currentTurn = nextTurns[index];
  if (currentTurn === undefined) {
    return turns;
  }

  nextTurns[index] = update(currentTurn);
  return nextTurns;
}

type BufferedItemUpdate = {
  turn_id: string;
  delta: string;
};

type PendingUserInputDequeue = {
  nextSlot: null;
  text: string | null;
};

const UNKNOWN_TOOL_NAME = "unknown";
const PENDING_USER_INPUT_TIMEOUT_MS = 7000;
const PENDING_USER_INPUT_TIMEOUT_WARNING =
  "Last input timed out waiting for a turn start; please retry.";

function toFinalLines(finalText: string): string[] {
  const pushed = reduceLineBuffer(INITIAL_LINE_BUFFER_STATE, {
    type: "push",
    delta: finalText,
  });
  return reduceLineBuffer(pushed, { type: "flush" }).committed;
}

function toHydratedTurnState(
  turn: Extract<ProtocolEvent, { type: "session.hydrated" }>["turns"][number],
): TurnState {
  return {
    turn_id: turn.turn_id,
    userText: turn.user_text,
    assistantLines:
      turn.assistant_text.length > 0 ? toFinalLines(turn.assistant_text) : [],
    partialLine: "",
    toolCalls: {},
    status: "completed",
    error: null,
    usage: null,
    compaction: {
      status: "idle",
      detail: null,
    },
  };
}

function applyItemStartedEvent(
  state: TurnsViewState,
  event: Extract<ProtocolEvent, { type: "item.started" }>,
): TurnsViewState {
  if (event.item_kind !== "tool_call") {
    return state;
  }

  const nextTurns = updateTurn(state.turns, event.turn_id, (turn) => {
    const existing = turn.toolCalls[event.item_id];
    const nextToolCall: ToolCallState = {
      item_id: event.item_id,
      name: event.name ?? existing?.name ?? UNKNOWN_TOOL_NAME,
      arguments: event.arguments ?? existing?.arguments ?? null,
      status: "pending",
      content: existing?.content ?? null,
    };

    return {
      ...turn,
      toolCalls: {
        ...turn.toolCalls,
        [event.item_id]: nextToolCall,
      },
    };
  });

  if (nextTurns === state.turns) {
    return state;
  }

  return {
    ...state,
    turns: nextTurns,
  };
}

function applyItemCompletedEvent(
  state: TurnsViewState,
  event: Extract<ProtocolEvent, { type: "item.completed" }>,
): TurnsViewState {
  if (event.item_kind !== "tool_result") {
    return state;
  }

  const nextTurns = updateTurn(state.turns, event.turn_id, (turn) => {
    const existing = turn.toolCalls[event.item_id];
    const nextToolCall: ToolCallState = {
      item_id: event.item_id,
      name: existing?.name ?? UNKNOWN_TOOL_NAME,
      arguments: existing?.arguments ?? null,
      status: "done",
      content: event.content,
    };

    return {
      ...turn,
      toolCalls: {
        ...turn.toolCalls,
        [event.item_id]: nextToolCall,
      },
    };
  });

  if (nextTurns === state.turns) {
    return state;
  }

  return {
    ...state,
    turns: nextTurns,
  };
}

function applyItemUpdatedDelta(
  state: TurnsViewState,
  update: BufferedItemUpdate,
): TurnsViewState {
  if (update.delta.length === 0) {
    return state;
  }

  const nextTurns = updateTurn(state.turns, update.turn_id, (turn) => {
    const nextBuffer = reduceLineBuffer(
      {
        committed: turn.assistantLines,
        partial: turn.partialLine,
      },
      {
        type: "push",
        delta: update.delta,
      },
    );

    return {
      ...turn,
      assistantLines: nextBuffer.committed,
      partialLine: nextBuffer.partial,
    };
  });

  if (nextTurns === state.turns) {
    return state;
  }

  return {
    ...state,
    turns: nextTurns,
  };
}

export function reduceTurns(
  state: TurnsViewState,
  event: ProtocolEvent,
): TurnsViewState {
  switch (event.type) {
    case "thread.started":
      if (state.threadId !== null && state.threadId !== event.thread_id) {
        return {
          threadId: event.thread_id,
          turns: [],
        };
      }

      return {
        ...state,
        threadId: event.thread_id,
      };
    case "turn.started": {
      if (state.turns.some((turn) => turn.turn_id === event.turn_id)) {
        return state;
      }

      return {
        ...state,
        turns: [
          ...state.turns,
          {
            turn_id: event.turn_id,
            userText: "",
            assistantLines: [],
            partialLine: "",
            toolCalls: {},
            status: "active",
            error: null,
            usage: null,
            compaction: {
              status: "pending",
              detail: null,
            },
          },
        ],
      };
    }
    case "context.compacted": {
      const nextTurns = updateTurn(state.turns, event.turn_id, (turn) => ({
        ...turn,
        compaction: {
          status: "triggered",
          detail: event,
        },
      }));

      if (nextTurns === state.turns) {
        return state;
      }

      return {
        ...state,
        turns: nextTurns,
      };
    }
    case "turn.completed": {
      const nextTurns = updateTurn(state.turns, event.turn_id, (turn) => ({
        ...turn,
        assistantLines:
          event.final_text.length > 0
            ? toFinalLines(event.final_text)
            : reduceLineBuffer(
                {
                  committed: turn.assistantLines,
                  partial: turn.partialLine,
                },
                { type: "flush" },
              ).committed,
        partialLine: "",
        status: "completed",
        error: null,
        usage: event.usage,
        compaction:
          turn.compaction.status === "pending"
            ? { status: "idle", detail: null }
            : turn.compaction,
      }));

      if (nextTurns === state.turns) {
        return state;
      }

      return {
        ...state,
        turns: nextTurns,
      };
    }
    case "turn.failed": {
      const nextTurns = updateTurn(state.turns, event.turn_id, (turn) => {
        const nextBuffer = reduceLineBuffer(
          {
            committed: turn.assistantLines,
            partial: turn.partialLine,
          },
          { type: "flush" },
        );

        return {
          ...turn,
          assistantLines: nextBuffer.committed,
          partialLine: nextBuffer.partial,
          status: "failed",
          error: event.error,
          compaction:
            turn.compaction.status === "pending"
              ? { status: "idle", detail: null }
              : turn.compaction,
        };
      });

      if (nextTurns === state.turns) {
        return state;
      }

      return {
        ...state,
        turns: nextTurns,
      };
    }
    case "item.started":
      return applyItemStartedEvent(state, event);
    case "item.completed":
      return applyItemCompletedEvent(state, event);
    case "session.hydrated":
      if (state.threadId !== null && state.threadId !== event.thread_id) {
        return state;
      }
      return {
        threadId: event.thread_id,
        turns: event.turns.map(toHydratedTurnState),
      };
    case "approval.request":
    case "session.listed":
    case "session.status":
    case "slash.unknown":
    case "slash.blocked":
    case "session.error":
      return state;
    case "item.updated":
      return applyItemUpdatedDelta(state, {
        turn_id: event.turn_id,
        delta: event.delta,
      });
    default: {
      const exhaustiveCheck: never = event;
      void exhaustiveCheck;
      return state;
    }
  }
}

export function reduceTurnsSequence(
  state: TurnsViewState,
  events: readonly ProtocolEvent[],
): TurnsViewState {
  let nextState = state;
  for (const event of events) {
    nextState = reduceTurns(nextState, event);
  }
  return nextState;
}

export function turnsReducer(state: TurnsViewState, action: TurnsAction): TurnsViewState {
  if (action.type === "reset") {
    return INITIAL_TURNS_STATE;
  }
  if (action.type === "item.updated.batch") {
    let nextState = state;
    for (const update of action.updates) {
      nextState = applyItemUpdatedDelta(nextState, update);
    }
    return nextState;
  }
  if (action.type === "user.input") {
    const nextTurns = updateTurn(state.turns, action.turn_id, (turn) => ({
      ...turn,
      userText: action.text,
    }));
    if (nextTurns === state.turns) {
      return state;
    }
    return { ...state, turns: nextTurns };
  }
  return reduceTurns(state, action.event);
}

export function enqueuePendingUserInput(
  slot: string | null,
  text: string,
): {
  accepted: boolean;
  nextSlot: string | null;
} {
  if (slot !== null) {
    return {
      accepted: false,
      nextSlot: slot,
    };
  }
  return {
    accepted: true,
    nextSlot: text,
  };
}

export function dequeuePendingUserInput(
  slot: string | null,
): PendingUserInputDequeue {
  return {
    nextSlot: null,
    text: slot,
  };
}

type TurnsDispatch = {
  hasPendingUserInput: boolean;
  pendingUserInputWarning: string | null;
  queueUserInput: (text: string) => boolean;
  setUserText: (turn_id: string, text: string) => void;
};

export function useTurns(
  events: readonly ProtocolEvent[],
): TurnsViewState & TurnsDispatch {
  const [state, dispatch] = useReducer(turnsReducer, INITIAL_TURNS_STATE);
  const lastProcessedEvent = useRef<ProtocolEvent | null>(null);
  const pendingItemUpdates = useRef<Map<string, string>>(new Map());
  const pendingFlushHandle = useRef<NodeJS.Immediate | null>(null);
  const pendingUserInput = useRef<string | null>(null);
  const pendingUserInputTimeout = useRef<NodeJS.Timeout | null>(null);
  const [hasPendingUserInput, setHasPendingUserInput] = useState(false);
  const [pendingUserInputWarning, setPendingUserInputWarning] = useState<string | null>(null);

  const flushPendingItemUpdates = useCallback((): void => {
    if (pendingItemUpdates.current.size === 0) {
      return;
    }

    const updates: BufferedItemUpdate[] = [];
    for (const [turn_id, delta] of pendingItemUpdates.current.entries()) {
      if (delta.length > 0) {
        updates.push({ turn_id, delta });
      }
    }
    pendingItemUpdates.current.clear();

    if (updates.length === 0) {
      return;
    }

    dispatch({
      type: "item.updated.batch",
      updates,
    });
  }, []);

  useEffect(() => {
    const cancelScheduledFlush = (): void => {
      if (pendingFlushHandle.current === null) {
        return;
      }
      clearImmediate(pendingFlushHandle.current);
      pendingFlushHandle.current = null;
    };

    const flushPendingSynchronously = (): void => {
      cancelScheduledFlush();
      flushPendingItemUpdates();
    };

    const schedulePendingFlush = (): void => {
      if (
        pendingFlushHandle.current !== null ||
        pendingItemUpdates.current.size === 0
      ) {
        return;
      }

      pendingFlushHandle.current = setImmediate(() => {
        pendingFlushHandle.current = null;
        flushPendingItemUpdates();
      });
    };

    if (events.length === 0) {
      cancelScheduledFlush();
      pendingItemUpdates.current.clear();
      pendingUserInput.current = null;
      if (pendingUserInputTimeout.current !== null) {
        clearTimeout(pendingUserInputTimeout.current);
        pendingUserInputTimeout.current = null;
      }
      setHasPendingUserInput(false);
      setPendingUserInputWarning(null);
      if (lastProcessedEvent.current !== null) {
        dispatch({ type: "reset" });
      }
      lastProcessedEvent.current = null;
      return;
    }

    const unprocessedEvents = sliceUnprocessedEvents(
      events,
      lastProcessedEvent.current,
    );
    for (const event of unprocessedEvents) {
      if (event.type === "item.updated") {
        const currentDelta = pendingItemUpdates.current.get(event.turn_id) ?? "";
        pendingItemUpdates.current.set(event.turn_id, `${currentDelta}${event.delta}`);
        continue;
      }

      flushPendingSynchronously();
      dispatch({
        type: "event",
        event,
      });
      if (event.type === "turn.started") {
        const { nextSlot, text } = dequeuePendingUserInput(
          pendingUserInput.current,
        );
        pendingUserInput.current = nextSlot;
        if (pendingUserInputTimeout.current !== null) {
          clearTimeout(pendingUserInputTimeout.current);
          pendingUserInputTimeout.current = null;
        }
        setHasPendingUserInput(false);
        setPendingUserInputWarning(null);
        if (text !== null) {
          dispatch({
            type: "user.input",
            turn_id: event.turn_id,
            text,
          });
        }
      }
    }

    schedulePendingFlush();
    const latestEvent = events[events.length - 1];
    lastProcessedEvent.current = latestEvent ?? null;
  }, [events, flushPendingItemUpdates]);

  useEffect(
    () => () => {
      if (pendingFlushHandle.current !== null) {
        clearImmediate(pendingFlushHandle.current);
        pendingFlushHandle.current = null;
      }
      pendingItemUpdates.current.clear();
      pendingUserInput.current = null;
      if (pendingUserInputTimeout.current !== null) {
        clearTimeout(pendingUserInputTimeout.current);
        pendingUserInputTimeout.current = null;
      }
    },
    [],
  );

  const queueUserInput = useCallback((text: string): boolean => {
    const { accepted, nextSlot } = enqueuePendingUserInput(
      pendingUserInput.current,
      text,
    );
    pendingUserInput.current = nextSlot;
    if (!accepted) {
      return false;
    }

    setHasPendingUserInput(true);
    setPendingUserInputWarning(null);
    if (pendingUserInputTimeout.current !== null) {
      clearTimeout(pendingUserInputTimeout.current);
    }
    pendingUserInputTimeout.current = setTimeout(() => {
      pendingUserInput.current = null;
      pendingUserInputTimeout.current = null;
      setHasPendingUserInput(false);
      setPendingUserInputWarning(PENDING_USER_INPUT_TIMEOUT_WARNING);
    }, PENDING_USER_INPUT_TIMEOUT_MS);
    return true;
  }, []);

  const setUserText = useCallback(
    (turn_id: string, text: string) => {
      dispatch({ type: "user.input", turn_id, text });
    },
    [],
  );

  return {
    ...state,
    hasPendingUserInput,
    pendingUserInputWarning,
    queueUserInput,
    setUserText,
  };
}
