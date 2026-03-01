import {
  formatAssistantMessageLines,
  formatUserMessageLines,
  renderSectionsForTurn,
  summarizeApprovalDebugLinesForTurn,
  toolCallsInDisplayOrder,
  summarizeToolCallsForTurn,
} from "../components/ChatView.js";
import type { ApprovalDecisionLog } from "../hooks/useApprovalQueue.js";
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

describe("formatUserMessageLines", () => {
  test("prefixes each line with shell-style quote marker", () => {
    expect(formatUserMessageLines("first line\nsecond line")).toEqual([
      "> first line",
      "> second line",
    ]);
  });
});

describe("formatAssistantMessageLines", () => {
  test("prefixes first line and indents continuation lines", () => {
    expect(formatAssistantMessageLines(["first", "second"])).toEqual([
      "• first",
      "  second",
    ]);
  });

  test("returns empty list when there is no assistant output", () => {
    expect(formatAssistantMessageLines([])).toEqual([]);
  });
});

describe("renderSectionsForTurn", () => {
  test("orders sections as user then assistant when no tool calls exist", () => {
    expect(
      renderSectionsForTurn(
        baseTurn({
          toolCalls: {},
          assistantLines: ["hello"],
        }),
      ),
    ).toEqual(["user", "assistant"]);
  });

  test("orders sections as user then tool then assistant", () => {
    expect(
      renderSectionsForTurn(
        baseTurn({
          toolCalls: {
            item_1: {
              item_id: "item_1",
              name: "shell",
              arguments: "{\"command\":\"ls -lrt\"}",
              status: "done",
              content: "ok",
            },
          },
          assistantLines: ["done"],
        }),
      ),
    ).toEqual(["user", "tool", "assistant"]);
  });
});

describe("toolCallsInDisplayOrder", () => {
  test("returns tool calls in insertion order for stable item_id keyed rendering", () => {
    const turn = baseTurn({
      toolCalls: {
        item_2: {
          item_id: "item_2",
          name: "write_file",
          arguments: null,
          status: "done",
          content: "ok",
        },
        item_1: {
          item_id: "item_1",
          name: "shell",
          arguments: "{\"command\":\"ls -lrt\"}",
          status: "pending",
          content: null,
        },
      },
    });

    const ordered = toolCallsInDisplayOrder(turn);
    expect(ordered.map((toolCall) => toolCall.item_id)).toEqual([
      "item_2",
      "item_1",
    ]);
  });
});

describe("summarizeApprovalDebugLinesForTurn", () => {
  test("shows fresh prompt approval decision with shell command preview", () => {
    const decisionLog: ApprovalDecisionLog[] = [
      {
        request_id: "req_1",
        turn_id: "turn_1",
        tool: "shell",
        preview: JSON.stringify({
          mode: "shell",
          command_preview: "ls -lrt",
          timeout_ms: 5000,
        }),
        decision: "approved",
        source: "fresh_prompt",
      },
    ];

    expect(
      summarizeApprovalDebugLinesForTurn(
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
        decisionLog,
        "on-request",
      ),
    ).toEqual([
      'Approval (fresh_prompt): approved once for shell command="ls -lrt"',
    ]);
  });

  test("shows likely cache-hit line when shell call has no prompt log", () => {
    expect(
      summarizeApprovalDebugLinesForTurn(
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
        [],
        "on-request",
      ),
    ).toEqual([
      "Approval: no prompt for shell (likely session-cache hit)",
    ]);
  });
});
