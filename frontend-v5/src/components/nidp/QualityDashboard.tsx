import { RefreshCw, Loader2, ShieldCheck, AlertTriangle, XCircle } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { NidpError } from "./NidpError";
import { useQuery } from "@tanstack/react-query";

interface QualityScore {
  target_date: string;
  domain: string;
  overall_score: number;
  accuracy: number;
  consistency: number;
  completeness: number;
  freshness: number;
  auditability: number;
  confidence: number;
  certification: string;
  publish_decision: string;
}
interface ConsistencyRun {
  target_date: string;
  domain: string;
  status: string;
  rules_run: number;
  rules_failed: number;
  findings_count: number;
  has_block: boolean;
  started_at: string;
}
interface QualitySummary {
  quality: QualityScore[];
  certified?: boolean;
  gate?: { passed: boolean };
  exceptions?: number;
  errors?: string[];
}
interface ConsistencyData { runs: ConsistencyRun[]; findings: unknown[]; errors: string[] }

const STATUS_TONE: Record<string, "good" | "warm" | "neg" | "default"> = {
  OK: "good", PASS: "good", PASSED: "good",
  PARTIAL: "warm", REVIEW: "warm",
  FAILED: "neg", REJECT: "neg",
};

function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.round((value / max) * 100);
  const color = pct >= 80 ? "bg-pos" : pct >= 60 ? "bg-warm" : "bg-neg";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-ink-2 w-10 text-right shrink-0">{value.toFixed(1)}</span>
    </div>
  );
}

export function QualityDashboard() {
  const { data: summary, isFetching: loadingQ, refetch: refetchQ, error: errQ } = useQuery({
    queryKey: ["nidp", "quality", "summary"],
    queryFn: () => http<QualitySummary>({ path: "/api/admin/nidp/quality/summary", timeoutMs: 20_000 }).then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  const { data: consistency, isFetching: loadingC, refetch: refetchC, error: errC } = useQuery({
    queryKey: ["nidp", "quality", "consistency"],
    queryFn: () => http<ConsistencyData>({ path: "/api/admin/nidp/quality/consistency", timeoutMs: 20_000 }).then((r) => r.data),
    staleTime: 5 * 60_000,
  });

  const isFetching = loadingQ || loadingC;
  const refetch = () => { refetchQ(); refetchC(); };

  // Group quality scores by domain
  const byDomain = (summary?.quality ?? []).reduce<Record<string, QualityScore[]>>((acc, q) => {
    (acc[q.domain] ??= []).push(q); return acc;
  }, {});
  const latestByDomain = Object.entries(byDomain).map(([domain, rows]) => ({
    domain,
    latest: rows.sort((a, b) => b.target_date.localeCompare(a.target_date))[0],
  }));

  const DIMS: Array<{ key: keyof QualityScore; label: string }> = [
    { key: "accuracy", label: "Accuracy" },
    { key: "consistency", label: "Consistency" },
    { key: "completeness", label: "Completeness" },
    { key: "freshness", label: "Freshness" },
    { key: "auditability", label: "Auditability" },
  ];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
            <ShieldCheck className="w-5 h-5 text-accent" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-ink">Data Quality</h2>
            <p className="text-xs text-ink-3">Quality scores · consistency gate · rule findings</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {summary?.gate && (
            <Badge tone={summary.gate.passed ? "good" : "neg"}>
              Gate {summary.gate.passed ? "passed" : "failed"}
            </Badge>
          )}
          {summary?.exceptions != null && summary.exceptions > 0 && (
            <Badge tone="warm"><AlertTriangle className="w-3 h-3" /> {summary.exceptions} exceptions</Badge>
          )}
          <Button size="sm" variant="outline" onClick={refetch} disabled={isFetching}>
            {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </Button>
        </div>
      </div>

      {(errQ || errC) && <NidpError err={errQ ?? errC} />}

      {/* Quality scores per domain */}
      {latestByDomain.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {latestByDomain.map(({ domain, latest: q }) => (
            <Card key={domain}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <div className="text-sm font-semibold text-ink capitalize">{domain}</div>
                    <div className="text-[10px] text-ink-3 font-mono">{q.target_date}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-xl font-bold text-ink">{q.overall_score.toFixed(1)}</div>
                    <Badge tone={STATUS_TONE[q.certification] ?? "default"}>{q.certification}</Badge>
                  </div>
                </div>
                <div className="space-y-1.5">
                  {DIMS.map(({ key, label }) => (
                    <div key={key} className="flex items-center gap-2 text-xs">
                      <span className="text-ink-3 w-24 shrink-0">{label}</span>
                      <ScoreBar value={q[key] as number} />
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <span className="text-[10px] text-ink-3">Publish:</span>
                  <Badge tone={STATUS_TONE[q.publish_decision] ?? "default"}>{q.publish_decision}</Badge>
                  <span className="text-[10px] text-ink-3 ml-auto">confidence {q.confidence.toFixed(1)}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Consistency gate runs */}
      {(consistency?.runs ?? []).length > 0 && (
        <Card>
          <CardContent className="p-4">
            <CardLabel className="mb-3">Consistency Gate — Recent Runs</CardLabel>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-ink-3 border-b border-hairline">
                    <th className="text-left py-1.5 pr-3">Date</th>
                    <th className="text-left py-1.5 pr-3">Domain</th>
                    <th className="text-center py-1.5 pr-3">Status</th>
                    <th className="text-right py-1.5 pr-3">Rules run</th>
                    <th className="text-right py-1.5 pr-3">Failures</th>
                    <th className="text-right py-1.5">Findings</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {consistency!.runs.map((r, i) => (
                    <tr key={i} className="hover:bg-surface-1 transition-colors">
                      <td className="py-2 pr-3 font-mono text-ink-3">{r.target_date}</td>
                      <td className="py-2 pr-3 text-ink-2 capitalize">{r.domain}</td>
                      <td className="py-2 pr-3 text-center">
                        <div className="flex items-center justify-center gap-1">
                          <Badge tone={STATUS_TONE[r.status] ?? "default"}>{r.status}</Badge>
                          {r.has_block && <span title="Blocking failure"><XCircle className="w-3 h-3 text-neg" /></span>}
                        </div>
                      </td>
                      <td className="py-2 pr-3 text-right font-mono text-ink-2">{r.rules_run}</td>
                      <td className="py-2 pr-3 text-right font-mono">
                        <span className={r.rules_failed > 0 ? "text-neg font-semibold" : "text-pos"}>{r.rules_failed}</span>
                      </td>
                      <td className="py-2 text-right font-mono text-ink-2">{r.findings_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {(summary?.errors ?? []).length > 0 && (
        <div className="text-xs text-neg bg-[rgb(var(--neg)/0.06)] rounded-lg p-3 space-y-1">
          {summary!.errors!.map((e, i) => <div key={i}>{e}</div>)}
        </div>
      )}

      {!isFetching && !summary && !errQ && (
        <div className="text-center text-sm text-ink-3 py-8">No quality data returned.</div>
      )}
    </div>
  );
}
