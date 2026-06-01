import { useState } from "react";
import { Database, RefreshCw, Loader2, ChevronDown, ChevronRight, CheckCircle2, XCircle } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { useQuery } from "@tanstack/react-query";

interface FeedStatus {
  feed_name: string;
  last_run_at?: string;
  last_status?: string;
  lag_hours?: number;
  success_count?: number;
  failure_count?: number;
}

interface TableInfo {
  table_name: string;
  schema_name?: string;
  row_count?: number;
  first_date?: string;
  last_date?: string;
  stale?: boolean;
}

interface CatalogData {
  feeds?: FeedStatus[];
  tables?: TableInfo[];
  generated_at?: string;
}

function relTime(iso?: string) {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

const STATUS_TONE: Record<string, "good" | "neg" | "warm" | "default"> = {
  OK: "good", GREEN: "good", PARTIAL: "warm", FAILED: "neg", RUNNING: "accent" as "default",
};

export function DataCatalog() {
  const [expandedTable, setExpandedTable] = useState<string | null>(null);

  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ["nidp", "catalog"],
    queryFn: () => http<CatalogData>({ path: "/api/admin/nidp/catalog", timeoutMs: 30_000 }).then((r) => r.data),
    staleTime: 2 * 60_000,
  });

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database className="w-5 h-5 text-ink-2" />
          <span className="text-sm font-medium text-ink">Data Catalog</span>
          {data?.generated_at && <span className="text-xs text-ink-3">· refreshed {relTime(data.generated_at)}</span>}
        </div>
        <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
        </Button>
      </div>

      {error && <div className="text-sm text-neg bg-[rgb(var(--neg)/0.08)] rounded-lg p-3">Failed to load catalog: {String(error)}</div>}

      {/* Feeds */}
      {(data?.feeds ?? []).length > 0 && (
        <Card>
          <CardContent className="p-4">
            <CardLabel className="mb-3">Feed Status ({data!.feeds!.length})</CardLabel>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-ink-3 border-b border-hairline">
                    <th className="text-left py-1.5 pr-3 font-mono">Feed</th>
                    <th className="text-left py-1.5 pr-3">Status</th>
                    <th className="text-left py-1.5 pr-3">Last run</th>
                    <th className="text-right py-1.5 pr-3">Lag</th>
                    <th className="text-right py-1.5">OK / Fail</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {data!.feeds!.map((f) => (
                    <tr key={f.feed_name} className="hover:bg-surface-1 transition-colors">
                      <td className="py-2 pr-3 font-mono text-ink-2">{f.feed_name}</td>
                      <td className="py-2 pr-3">
                        {f.last_status
                          ? <Badge tone={STATUS_TONE[f.last_status] ?? "default"}>{f.last_status}</Badge>
                          : <span className="text-ink-3">—</span>
                        }
                      </td>
                      <td className="py-2 pr-3 text-ink-3">{relTime(f.last_run_at)}</td>
                      <td className="py-2 pr-3 text-right font-mono text-ink-2">{f.lag_hours != null ? `${f.lag_hours.toFixed(1)}h` : "—"}</td>
                      <td className="py-2 text-right font-mono">
                        <span className="text-pos">{f.success_count ?? 0}</span>
                        <span className="text-ink-3"> / </span>
                        <span className="text-neg">{f.failure_count ?? 0}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tables */}
      {(data?.tables ?? []).length > 0 && (
        <Card>
          <CardContent className="p-4">
            <CardLabel className="mb-3">Table Inventory ({data!.tables!.length})</CardLabel>
            <div className="space-y-1">
              {data!.tables!.map((t) => {
                const key = `${t.schema_name}.${t.table_name}`;
                const expanded = expandedTable === key;
                return (
                  <div key={key} className="rounded-lg border border-hairline overflow-hidden">
                    <button
                      className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-surface-1 transition-colors text-left"
                      onClick={() => setExpandedTable(expanded ? null : key)}
                    >
                      {expanded ? <ChevronDown className="w-3.5 h-3.5 text-ink-3 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-ink-3 shrink-0" />}
                      <span className="font-mono text-ink-2 flex-1 truncate">{key}</span>
                      <span className="text-ink-3 shrink-0">{t.row_count?.toLocaleString() ?? "—"} rows</span>
                      {t.stale && <span className="text-warm text-[10px] font-bold">stale</span>}
                    </button>
                    {expanded && (
                      <div className="px-4 py-2 bg-surface-1 border-t border-hairline text-[11px] text-ink-3 flex gap-6">
                        <span>First: <strong className="text-ink-2">{t.first_date ?? "—"}</strong></span>
                        <span>Last: <strong className="text-ink-2">{t.last_date ?? "—"}</strong></span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {!isFetching && !data && !error && (
        <div className="text-center text-sm text-ink-3 py-8">No data returned from <code>/api/admin/nidp/catalog</code>.</div>
      )}
    </div>
  );
}
