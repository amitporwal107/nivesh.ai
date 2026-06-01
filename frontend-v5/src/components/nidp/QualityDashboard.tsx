import { RefreshCw, Loader2, ShieldCheck, AlertTriangle, TrendingDown } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { NidpError } from "./NidpError";
import { useQuery } from "@tanstack/react-query";

interface QualityMetric {
  feed_name: string;
  score?: number;
  accuracy?: number;
  consistency?: number;
  rule_failures?: number;
  sla_ok?: boolean;
  last_validated_at?: string;
}

interface QualitySummary {
  overall_score?: number;
  feeds: QualityMetric[];
  open_exceptions?: number;
  generated_at?: string;
}

function ScoreBar({ value }: { value?: number }) {
  if (value == null) return <span className="text-ink-3 text-xs">—</span>;
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "bg-pos" : pct >= 60 ? "bg-warm" : "bg-neg";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 bg-surface-2 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-ink-2">{pct}%</span>
    </div>
  );
}

export function QualityDashboard() {
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ["nidp", "quality"],
    queryFn: () => http<QualitySummary>({ path: "/api/admin/nidp/quality", timeoutMs: 20_000 }).then((r) => r.data),
    staleTime: 5 * 60_000,
  });

  const overallPct = data?.overall_score != null ? Math.round(data.overall_score * 100) : null;
  const overallTone = overallPct == null ? "default" : overallPct >= 80 ? "good" : overallPct >= 60 ? "warm" : "neg";

  return (
    <div className="space-y-5">
      {/* Summary header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
            <ShieldCheck className="w-5 h-5 text-accent" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-ink">Data Quality</h2>
            <p className="text-xs text-ink-3">Executive summary · quality metrics · rule failures · SLA monitor.</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {overallPct != null && <Badge tone={overallTone as "good" | "warm" | "neg" | "default"}>Overall {overallPct}%</Badge>}
          {data?.open_exceptions != null && data.open_exceptions > 0 && (
            <Badge tone="warm"><AlertTriangle className="w-3 h-3" /> {data.open_exceptions} exceptions</Badge>
          )}
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </Button>
        </div>
      </div>

      {error && <NidpError err={error} />}

      {/* Feed metrics table */}
      {(data?.feeds ?? []).length > 0 && (
        <Card>
          <CardContent className="p-4">
            <CardLabel className="mb-3">Per-Feed Quality Metrics</CardLabel>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-ink-3 border-b border-hairline">
                    <th className="text-left py-1.5 pr-4 font-mono">Feed</th>
                    <th className="text-left py-1.5 pr-4">Score</th>
                    <th className="text-left py-1.5 pr-4">Accuracy</th>
                    <th className="text-left py-1.5 pr-4">Consistency</th>
                    <th className="text-center py-1.5 pr-4">Rule Fails</th>
                    <th className="text-center py-1.5">SLA</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {data!.feeds.map((f) => (
                    <tr key={f.feed_name} className="hover:bg-surface-1 transition-colors">
                      <td className="py-2 pr-4 font-mono text-ink-2">{f.feed_name}</td>
                      <td className="py-2 pr-4"><ScoreBar value={f.score} /></td>
                      <td className="py-2 pr-4"><ScoreBar value={f.accuracy} /></td>
                      <td className="py-2 pr-4"><ScoreBar value={f.consistency} /></td>
                      <td className="py-2 pr-4 text-center font-mono">
                        {f.rule_failures != null
                          ? <span className={f.rule_failures > 0 ? "text-neg font-semibold" : "text-pos"}>{f.rule_failures}</span>
                          : "—"
                        }
                      </td>
                      <td className="py-2 text-center">
                        {f.sla_ok == null ? "—" : f.sla_ok
                          ? <ShieldCheck className="w-3.5 h-3.5 text-pos mx-auto" />
                          : <AlertTriangle className="w-3.5 h-3.5 text-neg mx-auto" />
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {!isFetching && !data && !error && (
        <div className="text-center text-sm text-ink-3 py-8">No quality data at <code>/api/admin/nidp/quality</code>.</div>
      )}
    </div>
  );
}
