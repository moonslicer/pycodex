import {
  buildPycodexArgs,
  isTuiDebugEnabled,
  resolveApprovalPolicy,
} from "../runtime/launch.js";

describe("buildPycodexArgs", () => {
  test("defaults to on-request approval", () => {
    const args = buildPycodexArgs({});

    expect(args).toEqual([
      "-m",
      "pycodex",
      "--tui-mode",
      "--approval",
      "on-request",
    ]);
  });

  test("allows approval override from environment", () => {
    const args = buildPycodexArgs({
      PYCODEX_TUI_APPROVAL: "never",
    });

    expect(args).toEqual([
      "-m",
      "pycodex",
      "--tui-mode",
      "--approval",
      "never",
    ]);
  });
});

describe("resolveApprovalPolicy", () => {
  test("defaults to on-request for unknown values", () => {
    expect(resolveApprovalPolicy({ PYCODEX_TUI_APPROVAL: "invalid" })).toBe(
      "on-request",
    );
  });
});

describe("isTuiDebugEnabled", () => {
  test("defaults to disabled", () => {
    expect(isTuiDebugEnabled({})).toBe(false);
  });

  test("enables with truthy env values", () => {
    expect(isTuiDebugEnabled({ PYCODEX_TUI_DEBUG: "1" })).toBe(true);
    expect(isTuiDebugEnabled({ PYCODEX_TUI_DEBUG: "true" })).toBe(true);
    expect(isTuiDebugEnabled({ PYCODEX_TUI_DEBUG: "YES" })).toBe(true);
  });

  test("disables for unknown values", () => {
    expect(isTuiDebugEnabled({ PYCODEX_TUI_DEBUG: "debug" })).toBe(false);
    expect(isTuiDebugEnabled({ PYCODEX_TUI_DEBUG: "0" })).toBe(false);
  });
});
