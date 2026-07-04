import { useEffect, useState } from "react";
import { TrendingUp, Loader2 } from "lucide-react";
import { api, type AnalyticsColumn, type AnalyticsResult } from "@/lib/api";

function fmtNumber(n: number): string {
  if (n >= 1e12) return (n / 1e12).toFixed(2) + " 万亿";
  if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
  if (n >= 1e4) return (n / 1e4).toFixed(2) + " 万";
  return n.toLocaleString();
}

function fmtCell(value: string | number | null | undefined, column: AnalyticsColumn): string {
  if (value === null || value === undefined || value === "") return "-";
  if (column.type === "number" && typeof value === "number") return fmtNumber(value);
  return String(value);
}

export function Ranking() {
  const [result, setResult] = useState<AnalyticsResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .runAnalysis("top-volume", { days: 20, limit: 100 })
      .then((analysis) => {
        if (!alive) return;
        setResult(analysis);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading ranking data...
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-20 text-center text-muted-foreground">
        <p className="text-red-400 mb-2">{error}</p>
        <p className="text-sm">
          Run{" "}
          <code className="bg-muted px-1 rounded">
            python -m src.data download
          </code>{" "}
          to populate data first.
        </p>
      </div>
    );
  }

  if (!result || result.rows.length === 0) {
    return (
      <div className="py-20 text-center text-muted-foreground">
        <p>No data available.</p>
        <p className="text-sm mt-2">
          Run{" "}
          <code className="bg-muted px-1 rounded">
            python -m src.data download
          </code>{" "}
          to populate daily OHLCV.
        </p>
      </div>
    );
  }

  const days = result.params.days ?? 20;
  const limit = result.params.limit ?? 100;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <TrendingUp className="h-6 w-6 text-emerald-400" />
          <div>
            <h1 className="text-xl font-bold">{result.title}</h1>
            <p className="text-sm text-muted-foreground">
              Top {String(limit)} by {String(days)} trading-day volume
            </p>
          </div>
        </div>
        <div className="text-xs text-muted-foreground tabular-nums">
          {String(result.meta["window_start"] ?? "-")} - {String(result.meta["window_end"] ?? "-")}
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-muted-foreground text-left">
            <tr>
              {result.columns.map((column) => (
                <th
                  key={column.key}
                  className={`px-4 py-3 whitespace-nowrap ${column.align === "right" ? "text-right" : "text-left"}`}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {result.rows.map((row, index) => (
              <tr
                key={String(row.code ?? index)}
                className="hover:bg-muted/30 transition-colors"
              >
                {result.columns.map((column) => (
                  <td
                    key={column.key}
                    className={`px-4 py-2.5 whitespace-nowrap ${
                      column.align === "right" ? "text-right tabular-nums" : "text-left"
                    } ${column.key === "code" ? "font-mono tabular-nums" : ""} ${
                      column.key === "rank" ? "text-muted-foreground" : ""
                    }`}
                  >
                    {fmtCell(row[column.key], column)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-muted-foreground">
        Data from DuckDB market database. Refresh after daily download.
      </p>
    </div>
  );
}
