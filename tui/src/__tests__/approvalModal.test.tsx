import {
  approvalPreviewLines,
  decisionForApprovalKey,
} from "../components/ApprovalModal.js";

describe("decisionForApprovalKey", () => {
  test("maps y/n/s/a to approval decisions", () => {
    expect(decisionForApprovalKey("y")).toBe("approved");
    expect(decisionForApprovalKey("n")).toBe("denied");
    expect(decisionForApprovalKey("s")).toBe("approved_for_session");
    expect(decisionForApprovalKey("a")).toBe("abort");
  });

  test("is case-insensitive", () => {
    expect(decisionForApprovalKey("Y")).toBe("approved");
    expect(decisionForApprovalKey("N")).toBe("denied");
  });

  test("returns null for unrelated input", () => {
    expect(decisionForApprovalKey("x")).toBeNull();
    expect(decisionForApprovalKey("")).toBeNull();
  });
});

describe("approvalPreviewLines", () => {
  test("shows parsed shell command preview and timeout", () => {
    const lines = approvalPreviewLines({
      thread_id: "thread_1",
      turn_id: "turn_1",
      request_id: "req_1",
      tool: "shell",
      preview: JSON.stringify({
        mode: "shell",
        command_preview: "ls -lrt",
        timeout_ms: 5000,
      }),
    });

    expect(lines).toEqual(["Command: ls -lrt", "Timeout: 5000ms"]);
  });

  test("falls back to raw preview for non-shell tools", () => {
    const lines = approvalPreviewLines({
      thread_id: "thread_1",
      turn_id: "turn_1",
      request_id: "req_1",
      tool: "write_file",
      preview: '{"arg_count": 2, "arg_keys": ["content", "file_path"]}',
    });

    expect(lines).toEqual([
      'Preview: {"arg_count": 2, "arg_keys": ["content", "file_path"]}',
    ]);
  });
});
