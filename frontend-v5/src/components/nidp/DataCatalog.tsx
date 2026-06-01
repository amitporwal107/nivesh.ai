import { useState } from "react";
import { Database, RefreshCw, Loader2, ChevronDown, ChevronRight } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { NidpError } from "./NidpError";
import { useQuery } from "@tanstack/react-query";

interface FeedDay { date: string; is_today: boolean; status: string | null; run_count: number }
interface Feed {
  ingester: string;
  job_name: string;
  source_class: string;
  expected_freq: string;
  schedule_cron: string | null;
  last_run_status: string | null;
  consecutive_failures: number;
  last_run_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_rows_inserted: number | null;
  last_run_duration_ms: number | null;
  success_count: number;
  failure_count: number;
  last_error_message: string | null;
  last_7_days: FeedDay[];
}
interface TableDesc { source?: string; stores?: string; use?: string }
interface TableInfo {
  table: string;
  domain: string;
  date_col: string | null;
  rows: number | null;
  first_at: string | null;
  last_at: string | null;
  description: TableDesc | string | null;
  error?: string | null;
}
interface DomainGroup { domain: string; tables: number; rows: number; earliest: string | null; latest: string | null }
interface ValidationRun { ingester: string; target_date: string; status: string; rules_run: number; rules_failed: number }
interface CatalogData {
  as_of: string;
  totals: { tables: number; feeds: number };
  by_domain: DomainGroup[];
  feeds: Feed[];
  tables: TableInfo[];
  validation: ValidationRun[];
}

const STATUS_TONE: Record<string, "good" | "neg" | "warm" | "default"> = {
  OK: "good", SUCCESS: "good", FAILED: "neg", PARTIAL: "warm", RUNNING: "default", SKIPPED: "default",
};
const DAY_COLOR: Record<string, string> = {
  OK: "bg-pos", SUCCESS: "bg-pos", FAILED: "bg-neg", PARTIAL: "bg-warm",
};

function relTime(iso?: string | null) {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function tableDesc(d: TableDesc | string | null): string {
  if (!d) return "";
  if (typeof d === "string") return d;
  return d.source ?? d.stores ?? d.use ?? "";
}

export function DataCatalog() {
  const [expandedTable, setExpandedTable] = useState<string | null>(null);
  const [expandedFeed, setExpandedFeed] = useState<string | null>(null);

  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ["nidp", "catalog"],
    queryFn: () => http<CatalogData>({ path: "/api/admin/nidp/catalog", timeoutMs: 60_000 }).then((r) => r.data),
    staleTime: 5 * 60_000,
  });

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database className="w-5 h-5 text-ink-2" />
          <span className="text-sm font-medium text-ink">Data Catalog</span>
          {data?.as_of && <span className="text-xs text-ink-3">· as of {relTime(data.as_of)}</span>}
          {data?.totals && (
            <span className="text-xs text-ink-3">· {data.totals.tables} tables · {data.totals.feeds} feeds</span>
          )}
        </div>
        <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
        </Button>
      </div>

      {error && <NidpError err={error} />}

      {/* Domain summary */}
      {(data?.by_domain ?? []).length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {data!.by_domain.map((d) => (
            <div key={d.domain} className="rounded-lg border border-hairline bg-surface-1 p-3">
              <div className="text-xs font-medium text-ink truncate">{d.domain}</div>
              <div className="text-lg font-semibold text-ink mt-0.5">{d.tables}</div>
              <div className="text-[10px] text-ink-3 font-mono">{d.rows?.toLocaleString() ?? "—"} rows</div>
              {d.latest && <div className="text-[10px] text-ink-3 mt-0.5">last: {d.latest.slice(0, 10)}</div>}
            </div>
          ))}
        </div>
      )}

      {/* Feeds (cron jobs) */}
      {(data?.feeds ?? []).length > 0 && (
        <Card>
          <CardContent className="p-4">
            <CardLabel className="mb-3">Feed Status — {data!.feeds.length} ingesters (cron)</CardLabel>
            <div className="space-y-1">
              {data!.feeds.map((f) => {
                const isExp = expandedFeed === f.ingester;
                const tone = STATUS_TONE[f.last_run_status ?? ""] ?? "default";
                return (
                  <div key={f.ingester} className="rounded-lg border border-hairline overflow-hidden">
                    <button
                      className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-1 transition-colors"
                      onClick={() => setExpandedFeed(isExp ? null : f.ingester)}
                    >
                      {isExp ? <ChevronDown className="w-3.5 h-3.5 text-ink-3 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-ink-3 shrink-0" />}
                      <span className="font-mono text-xs text-ink-2 flex-1 truncate">{f.ingester}</span>
                      {/* 7-day sparkbar */}
                      <div className="hidden sm:flex items-end gap-px h-4 shrink-0">
                        {f.last_7_days.map((day, i) => (
                          <div
                            key={i}
                            title={`${day.date}: ${day.status ?? "no run"} (${day.run_count} runs)`}
                            className={`w-2 rounded-sm ${day.status ? (DAY_COLOR[day.status] ?? "bg-surface-2") : "bg-surface-2"} ${day.is_today ? "ring-1 ring-accent" : ""} opacity-80`}
                            style={{ height: day.run_count > 0 ? "14px" : "4px" }}
                          />
                        ))}
                      </div>
                      {f.last_run_status && <Badge tone={tone}>{f.last_run_status}</Badge>}
                      <span className="text-[10px] text-ink-3 shrink-0 hidden md:inline">{relTime(f.last_run_at)}</span>
                      {f.consecutive_failures > 0 && (
                        <span className="text-[10px] font-bold text-neg shrink-0">{f.consecutive_failures}✗</span>
                      )}
                    </button>
                    {isExp && (
                      <div className="border-t border-hairline bg-surface-1 px-4 py-3 text-[11px] text-ink-3 space-y-1">
                        <div className="flex flex-wrap gap-x-6 gap-y-1">
                          <span>Source: <strong className="text-ink-2">{f.source_class}</strong></span>
                          <span>Freq: <strong className="text-ink-2">{f.expected_freq}</strong></span>
                          {f.schedule_cron && <span>Cron: <code className="text-ink-2">{f.schedule_cron}</code></span>}
                          <span>Last run: <strong className="text-ink-2">{relTime(f.last_run_at)}</strong></span>
                          {f.last_run_duration_ms != null && <span>Duration: <strong className="text-ink-2">{(f.last_run_duration_ms / 1000).toFixed(1)}s</strong></span>}
                          {f.last_rows_inserted != null && <span>Rows: <strong className="text-ink-2">{f.last_rows_inserted.toLocaleString()}</strong></span>}
                          <span>✓ {f.success_count} / ✗ {f.failure_count}</span>
                        </div>
                        {f.last_error_message && (
                          <div className="text-neg mt-1 font-mono text-[10px] bg-[rgb(var(--neg)/0.06)] rounded p-2 break-all">{f.last_error_message}</div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tables */}
      {(data?.tables ?? []).length > 0 && (
        <Card>
          <CardContent className="p-4">
            <CardLabel className="mb-3">Table Inventory — {data!.tables.length} tables</CardLabel>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-ink-3 border-b border-hairline">
                    <th className="text-left py-1.5 pr-3 font-mono">Table</th>
                    <th className="text-left py-1.5 pr-3">Domain</th>
                    <th className="text-right py-1.5 pr-3">Rows</th>
                    <th className="text-left py-1.5 pr-3">First</th>
                    <th className="text-left py-1.5">Latest</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {data!.tables.map((t) => {
                    const key = t.table;
                    const isExp = expandedTable === key;
                    const desc = tableDesc(t.description);
                    return (
                      <>
                        <tr
                          key={key}
                          className="hover:bg-surface-1 transition-colors cursor-pointer"
                          onClick={() => setExpandedTable(isExp ? null : key)}
                        >
                          <td className="py-2 pr-3">
                            <div className="flex items-center gap-1">
                              {isExp ? <ChevronDown className="w-3 h-3 text-ink-3 shrink-0" /> : <ChevronRight className="w-3 h-3 text-ink-3 shrink-0" />}
                              <span className="font-mono text-ink-2">{t.table}</span>
                              {t.error && <span className="text-neg ml-1" title={t.error}>⚠</span>}
                            </div>
                          </td>
                          <td className="py-2 pr-3 text-ink-3">{t.domain}</td>
                          <td className="py-2 pr-3 text-right font-mono text-ink-2">{t.rows?.toLocaleString() ?? "—"}</td>
                          <td className="py-2 pr-3 text-ink-3">{t.first_at?.slice(0, 10) ?? "—"}</td>
                          <td className="py-2 text-ink-3">{t.last_at?.slice(0, 10) ?? "—"}</td>
                        </tr>
                        {isExp && desc && (
                          <tr key={`${key}-desc`} className="bg-surface-1">
                            <td colSpan={5} className="px-6 py-2 text-[11px] text-ink-3 italic">{desc}</td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent validation runs */}
      {(data?.validation ?? []).length > 0 && (
        <Card>
          <CardContent className="p-4">
            <CardLabel className="mb-3">Recent Validation Runs</CardLabel>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-ink-3 border-b border-hairline">
                    <th className="text-left py-1.5 pr-3 font-mono">Ingester</th>
                    <th className="text-left py-1.5 pr-3">Target date</th>
                    <th className="text-center py-1.5 pr-3">Status</th>
                    <th className="text-right py-1.5 pr-3">Rules run</th>
                    <th className="text-right py-1.5">Failures</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {data!.validation.map((v, i) => (
                    <tr key={i} className="hover:bg-surface-1 transition-colors">
                      <td className="py-2 pr-3 font-mono text-ink-2">{v.ingester}</td>
                      <td className="py-2 pr-3 text-ink-3">{v.target_date}</td>
                      <td className="py-2 pr-3 text-center">
                        <Badge tone={STATUS_TONE[v.status] ?? "default"}>{v.status}</Badge>
                      </td>
                      <td className="py-2 pr-3 text-right font-mono text-ink-2">{v.rules_run}</td>
                      <td className="py-2 text-right font-mono">
                        <span className={v.rules_failed > 0 ? "text-neg font-semibold" : "text-pos"}>{v.rules_failed}</span>
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
        <div className="text-center text-sm text-ink-3 py-8">No catalog data returned.</div>
      )}
    </div>
  );
}
