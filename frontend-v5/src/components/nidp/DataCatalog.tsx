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

const FEED_DESCRIPTIONS: Record<string, string> = {
  bhavcopy:                  "NSE end-of-day prices — OHLCV + turnover for all listed securities. Runs at 13:00 IST weekdays.",
  delivery:                  "NSE security-wise delivery data — delivered qty + delivery % per stock. Settlement signal. 13:30 IST weekdays.",
  index_close:               "NSE index closing values (Nifty 50/100/500, Bank Nifty, etc.). 13:05 IST weekdays.",
  fii_dii:                   "FII & DII net buy/sell in cash + F&O — institutional flow signal. 13:45 IST weekdays.",
  bulk_deals:                "NSE bulk deals (>0.5% of listed shares). Reveals smart-money entry/exit. 13:15 IST weekdays.",
  block_deals:               "NSE block deals (>₹10 Cr). Negotiated institutional transfers. 13:20 IST weekdays.",
  corporate_actions:         "NSE corporate-action calendar — splits, bonuses, dividends, mergers. Daily.",
  rbi_yields:                "RBI G-Sec yield curve across tenors (1Y→30Y). Rate-regime context. 16:00 IST weekdays.",
  fred_macro:                "US macro indicators from FRED — DXY, US10Y, VIX, CPI, PCE. 17:00 IST daily.",
  nse_calendar:              "NSE trading-holiday calendar. Monthly on the 1st.",
  index_constituents:        "Nifty 50/100/200/500 membership — which symbols are in each index and when. Monthly.",
  snapshot_builder:          "Daily market + stock snapshots — frozen point-in-time payload for dashboards. 15:00 IST weekdays.",
  yfinance_backfill:         "Historical price backfill via yfinance. One-off runs only.",
  nse_financials:            "NSE XBRL quarterly results — revenue, PAT, EPS, debt. On demand after filing.",
  nse_shareholding:          "NSE shareholding pattern (quarterly) — promoter, FII, DII, MF, pledge %. On demand.",
  price_adjuster:            "Retroactively adjusts OHLCV for splits/bonuses/dividends to create continuous series.",
  nse_equity_master:         "NSE equity master file — symbol, ISIN, face value, series, listing date. On demand.",
  fno_bhavcopy:              "NSE F&O bhavcopy — per-contract OHLC + open interest for futures and options.",
  corporate_announcements_nse: "NSE corporate filings — classified by impact tier. Scraped every 5 min.",
  corporate_announcements_bse: "BSE corporate filings — classified by impact tier. Scraped every 5 min.",
  announcement_classifier:   "Haiku-powered impact classifier for announcements. Runs after each scrape.",
  document_parser:           "PDF/XLSX attachment parser for corporate filings. Feeds pgvector embeddings.",
  amfi_nav:                  "AMFI NAV for ~10k schemes daily. 20:00 IST Mon–Fri via NAVAll.txt.",
  amfi_circulars:            "AMFI notices/circulars — merger/rename/addendum events. Daily 09:00 IST.",
  amfi_nav_history:          "Historical NAV backfill from MFAPI. One-off bootstrap.",
  nse_financials_backfill:   "Historical NSE XBRL financial results backfill. One-off runs.",
  mf_disclosure_snapshot:    "AMC SID pages — TER, risk-o-meter, fund manager, AUM. Weekly scrape.",
  mf_holdings:               "Top-10 AMC monthly portfolio disclosures — per-security weight, sector. Monthly.",
  event_calendar:            "Corporate event calendar (AGM, board meetings, results dates). Daily.",
  event_day_poller:          "Intraday poller for events happening today. High-freq.",
  d1_prep:                   "D+1 market prep — computes next-day signals before market open.",
  intelligence:              "Portfolio intelligence sync — pushes derived insights to the app DB.",
  intelligence_layer:        "LLM-powered intelligence layer — copilot context enrichment.",
  quality_gate:              "DQ gate — runs consistency rules + quality scoring post-market-close.",
  mf_analytics_engine:       "V3 MF scoring engine — computes 6 composite scores per scheme.",
  technical_indicator_engine:"Technical indicators (RSI, MACD, Bollinger, ATR) per stock. Daily.",
  fundamental_engine:        "Fundamental scoring — P/E, ROE, debt ratios per stock. Daily.",
  portfolio_holdings_sync:   "Syncs user CAS portfolio holdings to the app database.",
  portfolio_intelligence_sync:"Syncs NIDP intelligence output to the app MongoDB per user.",
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
                        {(f.last_7_days ?? []).map((day, i) => (
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
                      <div className="border-t border-hairline bg-surface-1 px-4 py-3 text-[11px] text-ink-3 space-y-2">
                        {FEED_DESCRIPTIONS[f.ingester] && (
                          <p className="text-ink-2 text-xs">{FEED_DESCRIPTIONS[f.ingester]}</p>
                        )}
                        <div className="flex flex-wrap gap-x-6 gap-y-1">
                          <span>Freq: <strong className="text-ink-2">{f.expected_freq}</strong></span>
                          {f.schedule_cron
                            ? <span>Cron: <code className="text-ink-2 bg-surface-2 px-1 rounded">{f.schedule_cron}</code></span>
                            : <span className="text-ink-3">No cron — triggered by upstream</span>
                          }
                          <span>Last run: <strong className="text-ink-2">{relTime(f.last_run_at)}</strong></span>
                          {f.last_run_duration_ms != null && <span>Duration: <strong className="text-ink-2">{(f.last_run_duration_ms / 1000).toFixed(1)}s</strong></span>}
                          {f.last_rows_inserted != null && <span>Rows: <strong className="text-ink-2">{f.last_rows_inserted.toLocaleString()}</strong></span>}
                          <span>✓ {f.success_count} runs / ✗ {f.failure_count} fails</span>
                        </div>
                        {f.last_error_message && (
                          <div className="text-neg font-mono text-[10px] bg-[rgb(var(--neg)/0.06)] rounded p-2 break-all">{f.last_error_message}</div>
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
