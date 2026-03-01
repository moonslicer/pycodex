import {
  buildPycodexArgs,
  isTuiDebugEnabled,
  resolveApprovalPolicy,
  resolveSandboxPolicy,
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
      "--sandbox",
      "danger-full-access",
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
      "--sandbox",
      "danger-full-access",
    ]);
  });

  test("allows sandbox override from environment", () => {
    const args = buildPycodexArgs({
      PYCODEX_TUI_SANDBOX: "read-only",
    });

    expect(args).toEqual([
      "-m",
      "pycodex",
      "--tui-mode",
      "--approval",
      "on-request",
      "--sandbox",
      "read-only",
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

describe("resolveSandboxPolicy", () => {
  test("defaults to danger-full-access when unset", () => {
    expect(resolveSandboxPolicy({})).toBe("danger-full-access");
  });

  test("returns configured sandbox when value is valid", () => {
    expect(resolveSandboxPolicy({ PYCODEX_TUI_SANDBOX: "workspace-write" })).toBe(
      "workspace-write",
    );
  });

  test("falls back to danger-full-access for invalid values", () => {
    expect(resolveSandboxPolicy({ PYCODEX_TUI_SANDBOX: "invalid" })).toBe(
      "danger-full-access",
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
