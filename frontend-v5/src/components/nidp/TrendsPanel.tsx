import { RefreshCw, Loader2, TrendingUp } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

interface TrendPoint { date: string; value: number }
interface TrendSeries {
  metric: string;
  label: string;
  points: TrendPoint[];
  delta_pct?: number;
}
interface TrendsData { series: TrendSeries[]; window_days: number }

const WINDOWS = [7, 30, 90] as const;
type Window = typeof WINDOWS[number];

export function TrendsPanel() {
  const [window, setWindow] = useState<Window>(30);

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["nidp", "trends", window],
    queryFn: () => http<TrendsData>({ path: "/api/admin/nidp/trends", query: { days: window } }).then((r) => r.data).catch(() => null),
    staleTime: 10 * 60_000,
  });

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <TrendingUp className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Quality Trends</h2>
              <p className="text-xs text-ink-3">Score, accuracy, consistency, and rule failure trends.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border border-hairline overflow-hidden text-xs">
              {WINDOWS.map((w) => (
                <button key={w} onClick={() => setWindow(w)} className={`px-3 py-1.5 transition-colors ${window === w ? "bg-accent text-on-accent" : "text-ink-2 hover:bg-surface-2"}`}>{w}d</button>
              ))}
            </div>
            <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
              {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>

        {(data?.series ?? []).length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {data!.series.map((s) => {
              const last = s.points[s.points.length - 1]?.value;
              const lastPct = last != null ? Math.round(last * 100) : null;
              const color = s.delta_pct != null && s.delta_pct >= 0 ? "text-pos" : "text-neg";
              return (
                <div key={s.metric} className="rounded-lg border border-hairline p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-ink">{s.label}</span>
                    <div className="flex items-center gap-2">
                      {lastPct != null && <span className="text-sm font-semibold text-ink">{lastPct}%</span>}
                      {s.delta_pct != null && <span className={`text-xs font-medium ${color}`}>{s.delta_pct > 0 ? "+" : ""}{s.delta_pct.toFixed(1)}%</span>}
                    </div>
                  </div>
                  {/* Sparkline — simple bar representation */}
                  <div className="flex items-end gap-0.5 h-10">
                    {s.points.slice(-28).map((p, i) => {
                      const h = Math.max(2, Math.round((p.value ?? 0) * 40));
                      const barColor = p.value >= 0.8 ? "bg-pos" : p.value >= 0.6 ? "bg-warm" : "bg-neg";
                      return <div key={i} title={`${p.date}: ${Math.round(p.value * 100)}%`} className={`flex-1 rounded-sm ${barColor} opacity-70`} style={{ height: `${h}px` }} />;
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center text-sm text-ink-3 py-8">
            {isFetching ? "Loading trends…" : "No trend data at /api/admin/nidp/trends."}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
