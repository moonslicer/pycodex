import { useCallback, useEffect, useReducer, useRef } from "react";

import type { ProtocolEvent, TokenUsage } from "../protocol/types.js";

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

function splitFinalText(finalText: string): string[] {
  if (finalText.length === 0) {
    return [];
  }
  return finalText.split("\n");
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
        assistantLines: splitFinalText(event.final_text),
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
      const nextTurns = updateTurn(state.turns, event.turn_id, (turn) => ({
        ...turn,
        status: "failed",
        error: event.error,
      }));

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
    case "item.updated":
      return state;
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

function turnsReducer(state: TurnsViewState, action: TurnsAction): TurnsViewState {
  if (action.type === "reset") {
    return INITIAL_TURNS_STATE;
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

  useEffect(() => {
    if (events.length < processedEventCount.current) {
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

      dispatch({
        type: "event",
        event,
      });
    }

    processedEventCount.current = events.length;
  }, [events]);

  const setUserText = useCallback(
    (turn_id: string, text: string) => {
      dispatch({ type: "user.input", turn_id, text });
    },
    [],
  );

  return { ...state, setUserText };
}
