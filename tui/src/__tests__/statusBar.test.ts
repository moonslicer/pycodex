import {
  formatCompactionCount,
  formatCompactionSummary,
  formatContextMeter,
  formatUsageSummary,
} from "../components/StatusBar.js";

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

describe("formatCompactionSummary", () => {
  test("returns pending when compaction is pending", () => {
    expect(formatCompactionSummary("pending", null)).toBe("compaction: pending");
  });

  test("returns idle when no compaction detail is available", () => {
    expect(formatCompactionSummary("idle", null)).toBe("compaction: idle");
  });

  test("includes replacement and context threshold metrics when detail exists", () => {
    expect(
      formatCompactionSummary("triggered", {
        type: "context.compacted",
        thread_id: "thread_1",
        turn_id: "turn_1",
        strategy: "threshold_v1",
        implementation: "local_summary_v1",
        replaced_items: 6,
        estimated_prompt_tokens: 9100,
        context_window_tokens: 10000,
        remaining_ratio: 0.09,
        threshold_ratio: 0.2,
      }),
    ).toBe("compaction: triggered (replaced 6; context 91.0% / threshold 80.0%)");
  });
});

describe("formatContextMeter", () => {
  test("returns null when session status is missing", () => {
    expect(formatContextMeter(null)).toBeNull();
  });

  test("renders ascii context fill meter", () => {
    expect(
      formatContextMeter({
        type: "session.status",
        thread_id: "thread_1",
        turn_count: 2,
        input_tokens: 120000,
        output_tokens: 1234,
        estimated_prompt_tokens: 64000,
        context_window_tokens: 128000,
        compaction_count: 1,
      }),
    ).toBe("context: [#####-----] 50.0% (128k)");
  });
});

describe("formatCompactionCount", () => {
  test("hides compaction count when zero", () => {
    expect(formatCompactionCount(0)).toBeNull();
  });

  test("shows compaction count suffix when nonzero", () => {
    expect(formatCompactionCount(2)).toBe("compacted: 2x");
  });
});
