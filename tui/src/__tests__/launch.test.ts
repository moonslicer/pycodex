import { buildPycodexArgs } from "../runtime/launch.js";

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
