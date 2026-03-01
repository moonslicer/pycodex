import {
  previewToolCallContent,
  statusDotColorForToolCall,
  statusLabelForToolCall,
  summarizeToolCall,
} from "../components/ToolCallPanel.js";

describe("statusLabelForToolCall", () => {
  test("maps pending status", () => {
    expect(statusLabelForToolCall("pending")).toBe("pending");
  });

  test("maps done status", () => {
    expect(statusLabelForToolCall("done")).toBe("done");
  });

  test("maps error status", () => {
    expect(statusLabelForToolCall("error")).toBe("error");
  });
});

describe("statusDotColorForToolCall", () => {
  test("maps pending to yellow", () => {
    expect(statusDotColorForToolCall("pending")).toBe("yellow");
  });

  test("maps done to green", () => {
    expect(statusDotColorForToolCall("done")).toBe("green");
  });

  test("maps error to red", () => {
    expect(statusDotColorForToolCall("error")).toBe("red");
  });
});

describe("summarizeToolCall", () => {
  test("summarizes shell command with command preview", () => {
    expect(
      summarizeToolCall({
        item_id: "item_1",
        name: "shell",
        arguments: JSON.stringify({ command: "ls -lrt" }),
        status: "done",
        content: "ok",
      }),
    ).toBe("Ran shell: ls -lrt");
  });

  test("summarizes read_file with compact label", () => {
    expect(
      summarizeToolCall({
        item_id: "item_1",
        name: "read_file",
        arguments: JSON.stringify({ path: "README.md" }),
        status: "done",
        content: "ok",
      }),
    ).toBe("Read 1 file");
  });
});

describe("previewToolCallContent", () => {
  test("returns empty preview for missing content", () => {
    expect(previewToolCallContent(null)).toEqual({
      lines: [],
      truncated: false,
    });
  });

  test("splits lines and keeps blank lines", () => {
    expect(previewToolCallContent("line one\n\nline three")).toEqual({
      lines: ["line one", "", "line three"],
      truncated: false,
    });
  });

  test("truncates long output at requested max line count", () => {
    expect(previewToolCallContent("l1\nl2\nl3", 2)).toEqual({
      lines: ["l1", "l2"],
      truncated: true,
    });
  });
});
