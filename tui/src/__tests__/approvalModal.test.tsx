import { decisionForApprovalKey } from "../components/ApprovalModal.js";

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
