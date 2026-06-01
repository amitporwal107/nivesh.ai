import { RefreshCw, Loader2, HardDriveDownload, CheckCircle2, XCircle, Clock } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { useQuery } from "@tanstack/react-query";

interface FeedReadiness {
  feed_name: string;
  source: string;
  cadence: string;
  coverage_days?: number;
  coverage_pct?: number;
  cert_status: "certified" | "partial" | "not_certified";
  in_flight?: boolean;
  last_backfill_at?: string;
}

const CERT_TONE: Record<string, "good" | "warm" | "neg"> = {
  certified: "good", partial: "warm", not_certified: "neg",
};

export function BackfillPanel() {
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ["nidp", "backfill"],
    queryFn: () => http<{ feeds: FeedReadiness[] }>({ path: "/api/admin/nidp/backfill" }).then((r) => r.data).catch(() => ({ feeds: [] })),
    staleTime: 5 * 60_000,
  });

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <HardDriveDownload className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Backfill Readiness</h2>
              <p className="text-xs text-ink-3">Per-feed source · cadence · coverage matrix · cert status · in-flight runs.</p>
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </Button>
        </div>

        {error && <div className="text-sm text-neg bg-[rgb(var(--neg)/0.08)] rounded-lg p-3 mb-4">Failed to load backfill data: {String(error)}</div>}

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-ink-3 border-b border-hairline">
                <th className="text-left py-2 pr-3 font-mono">Feed</th>
                <th className="text-left py-2 pr-3">Source</th>
                <th className="text-left py-2 pr-3">Cadence</th>
                <th className="text-right py-2 pr-3">Coverage</th>
                <th className="text-center py-2 pr-3">Cert</th>
                <th className="text-center py-2">In-flight</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {(data?.feeds ?? []).map((f) => (
                <tr key={f.feed_name} className="hover:bg-surface-1 transition-colors">
                  <td className="py-2 pr-3 font-mono text-ink-2">{f.feed_name}</td>
                  <td className="py-2 pr-3 text-ink-3">{f.source}</td>
                  <td className="py-2 pr-3 text-ink-3">{f.cadence}</td>
                  <td className="py-2 pr-3 text-right">
                    {f.coverage_pct != null ? (
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${f.coverage_pct >= 80 ? "bg-pos" : f.coverage_pct >= 50 ? "bg-warm" : "bg-neg"}`} style={{ width: `${f.coverage_pct}%` }} />
                        </div>
                        <span className="font-mono text-ink-2 w-10 text-right">{f.coverage_pct}%</span>
                      </div>
                    ) : f.coverage_days != null ? (
                      <span className="text-ink-2">{f.coverage_days}d</span>
                    ) : "—"}
                  </td>
                  <td className="py-2 pr-3 text-center">
                    <Badge tone={CERT_TONE[f.cert_status]}>{f.cert_status.replace("_", " ")}</Badge>
                  </td>
                  <td className="py-2 text-center">
                    {f.in_flight ? <Clock className="w-3.5 h-3.5 text-warm mx-auto animate-pulse" /> : <span className="text-ink-3">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!isFetching && (data?.feeds ?? []).length === 0 && !error && (
            <div className="text-center text-sm text-ink-3 py-8">No backfill data at <code>/api/admin/nidp/backfill</code>.</div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
