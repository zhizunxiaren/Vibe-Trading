import { resolveChartIndicators } from "../chart-indicators";

describe("resolveChartIndicators", () => {
  const dates = ["2026-01-01", "2026-01-02", "2026-01-03"];

  it("keeps legacy indicator maps compatible and aligns values by time", () => {
    const indicators = resolveChartIndicators(
      {
        alpha_signal: [
          { time: "2026-01-01", value: 1.25 },
          { time: "2026-01-03", value: 1.5 },
        ],
      },
      dates,
    );

    expect(indicators).toEqual([
      {
        name: "ALPHA_SIGNAL",
        pane: "price",
        type: "line",
        values: [1.25, null, 1.5],
      },
    ]);
  });

  it("preserves custom indicator metadata for formula-driven series", () => {
    const indicators = resolveChartIndicators(
      [
        {
          name: "资金强度",
          pane: "sub",
          type: "bar",
          color: "#2563eb",
          precision: 4,
          points: [
            { time: "2026-01-02", value: 0.42 },
            { time: "2026-01-03", value: null },
          ],
        },
      ],
      dates,
    );

    expect(indicators).toEqual([
      {
        name: "资金强度",
        pane: "sub",
        type: "bar",
        color: "#2563eb",
        precision: 4,
        values: [null, 0.42, null],
      },
    ]);
  });

  it("returns an empty list when no custom indicators are supplied", () => {
    expect(resolveChartIndicators(undefined, dates)).toEqual([]);
  });
});
