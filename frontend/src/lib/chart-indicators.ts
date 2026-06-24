export type ChartIndicatorPane = "price" | "sub";
export type ChartIndicatorType = "line" | "bar";
export type ChartIndicatorLineStyle = "solid" | "dashed" | "dotted";

export interface ChartIndicatorPoint {
  time: string;
  value: number | null;
}

export interface ChartIndicatorSpec {
  name: string;
  points: ChartIndicatorPoint[];
  pane?: ChartIndicatorPane;
  type?: ChartIndicatorType;
  color?: string;
  precision?: number;
  lineStyle?: ChartIndicatorLineStyle;
}

export type LegacyChartIndicatorMap = Record<string, ChartIndicatorPoint[]>;
export type ChartIndicatorInput = LegacyChartIndicatorMap | ChartIndicatorSpec[];

export interface ResolvedChartIndicator {
  name: string;
  pane: ChartIndicatorPane;
  type: ChartIndicatorType;
  values: Array<number | null>;
  color?: string;
  precision?: number;
  lineStyle?: ChartIndicatorLineStyle;
}

function alignValues(points: ChartIndicatorPoint[], dates: string[]): Array<number | null> {
  const lookup = new Map(points.map((p) => [p.time, p.value]));
  return dates.map((date) => lookup.get(date) ?? null);
}

export function resolveChartIndicators(
  indicators: ChartIndicatorInput | undefined,
  dates: string[],
): ResolvedChartIndicator[] {
  if (!indicators) return [];

  if (Array.isArray(indicators)) {
    return indicators.map((indicator) => ({
      name: indicator.name,
      pane: indicator.pane ?? "price",
      type: indicator.type ?? "line",
      values: alignValues(indicator.points, dates),
      ...(indicator.color ? { color: indicator.color } : {}),
      ...(indicator.precision !== undefined ? { precision: indicator.precision } : {}),
      ...(indicator.lineStyle ? { lineStyle: indicator.lineStyle } : {}),
    }));
  }

  return Object.entries(indicators).map(([name, points]) => ({
    name: name.toUpperCase(),
    pane: "price",
    type: "line",
    values: alignValues(points, dates),
  }));
}
