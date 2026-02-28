import { useCallback, useEffect, useReducer, useRef } from "react";

import type { ProtocolEvent, TokenUsage } from "../protocol/types.js";
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
  usage: TokenUsage | null;
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

function toFinalLines(finalText: string): string[] {
  const pushed = reduceLineBuffer(INITIAL_LINE_BUFFER_STATE, {
    type: "push",
    delta: finalText,
  });
  return reduceLineBuffer(pushed, { type: "flush" }).committed;
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
          },
        ],
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
    case "item.completed":
    case "approval.request":
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

export type { TurnsAction };

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

export type TurnsDispatch = {
  setUserText: (turn_id: string, text: string) => void;
};

export function useTurns(
  events: readonly ProtocolEvent[],
): TurnsViewState & TurnsDispatch {
  const [state, dispatch] = useReducer(turnsReducer, INITIAL_TURNS_STATE);
  const processedEventCount = useRef(0);
  const pendingItemUpdates = useRef<Map<string, string>>(new Map());
  const pendingFlushHandle = useRef<NodeJS.Immediate | null>(null);

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

    if (events.length < processedEventCount.current) {
      cancelScheduledFlush();
      pendingItemUpdates.current.clear();
      dispatch({ type: "reset" });
      processedEventCount.current = 0;
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
    }

    schedulePendingFlush();
    processedEventCount.current = events.length;
  }, [events, flushPendingItemUpdates]);

  useEffect(
    () => () => {
      if (pendingFlushHandle.current !== null) {
        clearImmediate(pendingFlushHandle.current);
        pendingFlushHandle.current = null;
      }
      pendingItemUpdates.current.clear();
    },
    [],
  );

  const setUserText = useCallback(
    (turn_id: string, text: string) => {
      dispatch({ type: "user.input", turn_id, text });
    },
    [],
  );

  return { ...state, setUserText };
}
