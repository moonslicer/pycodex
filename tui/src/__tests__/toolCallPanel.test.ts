import {
  previewToolCallContent,
  statusLabelForToolCall,
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
