import { summarizeToolCallsForTurn } from "../components/ChatView.js";
import type { TurnState } from "../hooks/useTurns.js";

function baseTurn(overrides: Partial<TurnState> = {}): TurnState {
  return {
    turn_id: "turn_1",
    userText: "ls -lrt",
    assistantLines: [],
    partialLine: "",
    toolCalls: {},
    status: "completed",
    error: null,
    usage: null,
    ...overrides,
  };
}

describe("summarizeToolCallsForTurn", () => {
  test("shows no-tool message for completed turns with no tool calls", () => {
    expect(summarizeToolCallsForTurn(baseTurn())).toBe("No tool call this turn");
  });

  test("hides no-tool message for active turns", () => {
    expect(summarizeToolCallsForTurn(baseTurn({ status: "active" }))).toBeNull();
  });

  test("shows single tool call name", () => {
    expect(
      summarizeToolCallsForTurn(
        baseTurn({
          toolCalls: {
            item_1: {
              item_id: "item_1",
              name: "shell",
              arguments: "{\"command\":\"ls -lrt\"}",
              status: "done",
              content: "stdout:\n...",
            },
          },
        }),
      ),
    ).toBe("Tool called: shell");
  });

  test("shows distinct tool names in insertion order", () => {
    expect(
      summarizeToolCallsForTurn(
        baseTurn({
          toolCalls: {
            item_1: {
              item_id: "item_1",
              name: "shell",
              arguments: null,
              status: "done",
              content: "ok",
            },
            item_2: {
              item_id: "item_2",
              name: "write_file",
              arguments: null,
              status: "done",
              content: "ok",
            },
            item_3: {
              item_id: "item_3",
              name: "shell",
              arguments: null,
              status: "done",
              content: "ok",
            },
          },
        }),
      ),
    ).toBe("Tool calls: shell, write_file");
  });
});
