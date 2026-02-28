import { formatUsageSummary } from "../components/StatusBar.js";

describe("formatUsageSummary", () => {
  test("returns n/a when usage is unavailable", () => {
    expect(formatUsageSummary(null, null)).toBe("usage: n/a");
  });

  test("shows latest usage when only latest is available", () => {
    expect(
      formatUsageSummary(
        {
          input_tokens: 12,
          output_tokens: 8,
        },
        null,
      ),
    ).toBe("usage latest(in/out): 12/8");
  });

  test("shows total usage when only cumulative is available", () => {
    expect(
      formatUsageSummary(
        null,
        {
          input_tokens: 120,
          output_tokens: 64,
        },
      ),
    ).toBe("usage total(in/out): 120/64");
  });

  test("shows latest and cumulative usage together", () => {
    expect(
      formatUsageSummary(
        {
          input_tokens: 12,
          output_tokens: 8,
        },
        {
          input_tokens: 120,
          output_tokens: 64,
        },
      ),
    ).toBe("usage latest(in/out): 12/8 | total(in/out): 120/64");
  });
});
