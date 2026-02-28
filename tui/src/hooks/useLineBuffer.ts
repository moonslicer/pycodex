import { useReducer, type Dispatch } from "react";

export type LineBufferState = {
  committed: string[];
  partial: string;
};

export type LineBufferAction =
  | {
      type: "push";
      delta: string;
    }
  | {
      type: "flush";
    }
  | {
      type: "reset";
    };

export const INITIAL_LINE_BUFFER_STATE: LineBufferState = {
  committed: [],
  partial: "",
};

export function reduceLineBuffer(
  state: LineBufferState,
  action: LineBufferAction,
): LineBufferState {
  switch (action.type) {
    case "push": {
      const raw = `${state.partial}${action.delta}`;
      const segments = raw.split("\n");
      const partial = segments.pop() ?? "";

      return {
        committed: [...state.committed, ...segments],
        partial,
      };
    }
    case "flush":
      return {
        committed:
          state.partial.length > 0
            ? [...state.committed, state.partial]
            : [...state.committed],
        partial: "",
      };
    case "reset":
      return INITIAL_LINE_BUFFER_STATE;
    default: {
      const exhaustiveCheck: never = action;
      void exhaustiveCheck;
      return state;
    }
  }
}

export function useLineBuffer(): [
  LineBufferState,
  Dispatch<LineBufferAction>,
] {
  return useReducer(reduceLineBuffer, INITIAL_LINE_BUFFER_STATE);
}
