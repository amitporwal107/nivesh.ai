/**
 * Market Desk › Screener › Scan dashboard (docs/scan_builder/DESIGN.md §8). The owner's "simple dashboard": the 17 widgets of
 * Chartink dashboard 247498 computed on our own data (Kite live quotes over NSE end-of-day bars, fundamentals and company
 * results from our data platform), each card with its criteria always visible and its table. Real time: asked again every
 * 10 s while the market is open and the tab is visible (useMarketDashboard).
 *
 * A criterion the server could not apply (applied=false, e.g. a 15-minute condition) is dimmed with its reason in amber, so a
 * list is never mistaken for the full scan. Widgets the server marks pending or not computed show its note instead of a table.
 * Behind the `scan_builder` flag: with it off nothing is asked of the server. Reads GET /api/scan-builder/market-dashboard
 * only. Wording: scans and stocks that pass them; never buy / sell / target / stop loss / picks.
 */
import { useEffect, useMemo, useState, type CSSProperties, type MouseEvent } from "react";
import { useHref, useLocation } from "react-router-dom";
import { useMe } from "@/hooks/use-auth";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../../../../../components/ui";
import { useCopilotShell } from "../../../../../lib/shell-context";
import { useDesk } from "../../../context";
import { scanProblem, type ScanProblem } from "../scan-builder/scan-builder-data";
import {
  useMarketDashboard, type DashboardCell, type DashboardColumn, type DashboardCriterion, type DashboardWidget, type MarketDashboard,
} from "./market-dashboard-data";

const DASH = "–";
const fmt2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function useVisible(): boolean {
  const [v, setV] = useState(() => typeof document === "undefined" || document.visibilityState === "visible");
  useEffect(() => {
    const f = () => setV(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", f);
    return () => document.removeEventListener("visibilitychange", f);
  }, []);
  return v;
}

/** hh:mm:ss in IST for an ISO time; null when it does not parse. */
function istTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

/** A widget's as-of: an ISO time becomes "hh:mm:ss IST", anything else is shown as the server wrote it. */
function asOfText(v: string | null | undefined): string | null {
  if (!v) return null;
  if (/^\d{4}-\d{2}-\d{2}T/.test(v)) {
    const t = istTime(v);
    if (t) return `${t} IST`;
  }
  return v;
}

/** One cell as text: pct 2 dp + "%", price and number 2 dp, volume as an Indian-grouped whole number, text as is. */
export function cellText(v: DashboardCell | undefined, format: string): string {
  if (v === null || v === undefined || v === "") return DASH;
  if (typeof v === "string") return v;
  if (!Number.isFinite(v)) return DASH;
  if (format === "pct") return `${fmt2.format(v)}%`;
  if (format === "price" || format === "number") return fmt2.format(v);
  if (format === "volume") return Math.round(v).toLocaleString("en-IN");
  return String(v);
}

const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;

// ── the screen ───────────────────────────────────────────────────────────────────────────────────────────────────────

export default function ScanDashboard() {
  const me = useMe();
  const enabled = me.data?.features?.scan_builder === true;
  if (me.isPending) return <LoadingBlock label="Loading" rows={2} />;
  if (!enabled) {
    return (
      <div data-testid="sd-off">
        <EmptyBlock title="The Scan dashboard is not enabled for your account" body="It is being rolled out in stages. Nothing on this screen was calculated." />
      </div>
    );
  }
  return <DashboardOn />;
}

function problemTitle(p: ScanProblem | null): string {
  if (p?.code === "data_unavailable") return "The market data could not be loaded";
  if (p?.code === "feature_disabled") return "The Scan dashboard is not enabled for your account";
  return "The scan dashboard did not load";
}

function DashboardOn() {
  const q = useMarketDashboard();
  const desk = useDesk();
  const { mobile } = useCopilotShell();
  const visible = useVisible();
  const location = useLocation();
  const deskHref = useHref(location.pathname);
  const chartHref = (sym: string) => `${deskHref}?tab=trade&view=chart&sub=live&sym=${encodeURIComponent(sym)}`;

  if (q.isPending) {
    return (
      <div data-testid="sd-loading">
        <LoadingBlock label="Computing the scan dashboard" rows={6} />
        <p className="m-0" style={{ paddingTop: 8, fontSize: 12.5, color: "var(--cp-ink-3)" }}>
          The first answer of the day reads the market’s history on the server and can take up to a minute.
        </p>
      </div>
    );
  }
  if (!q.data) {
    const p = scanProblem(q.error);
    return (
      <div data-testid="sd-error" data-code={p?.code ?? "unexpected"}>
        <ErrorBlock title={problemTitle(p)} error={p?.message ?? q.error} onRetry={p?.code === "feature_disabled" ? undefined : () => { void q.refetch(); }} />
      </div>
    );
  }
  const d = q.data;
  const refreshProblem = q.isError ? scanProblem(q.error) : null;
  return (
    <div data-testid="scan-dashboard" data-mode={d.basis.mode} className="flex min-w-0 flex-col" style={{ gap: 14 }}>
      <DashHeader d={d} visible={visible} refreshing={q.isFetching} problem={refreshProblem} onRetry={() => { void q.refetch(); }} />
      <div data-testid="sd-grid" style={{ display: "grid", gridTemplateColumns: mobile ? "minmax(0, 1fr)" : "repeat(auto-fill, minmax(360px, 1fr))", gap: 14, alignItems: "start" }}>
        {d.widgets.map((w) => (
          <WidgetCard key={w.id} w={w} chartHref={chartHref} onOpenSymbol={(s) => desk.openChart(s)} />
        ))}
      </div>
      {d.widgets.length === 0 && (
        <EmptyBlock title="No widgets came back." body="The server answered without any widget. Try again in a minute." />
      )}
    </div>
  );
}

// ── header ───────────────────────────────────────────────────────────────────────────────────────────────────────────

function LiveChip({ open, visible, seconds }: { open: boolean; visible: boolean; seconds: number }) {
  const state = !open ? "closed" : visible ? "live" : "paused_hidden";
  const text = state === "live" ? `Live · every ${seconds} s` : state === "paused_hidden" ? "Paused · this tab is hidden" : "Market closed";
  return (
    <span data-testid="sd-live-chip" data-state={state} className="cp-pill" data-tone={state === "live" ? "mint" : undefined}>
      {state === "live" && <span aria-hidden className="cp-running" style={{ width: 6, height: 6, borderRadius: 999, background: "var(--mint)" }} />}
      {text}
    </span>
  );
}

function DashHeader({ d, visible, refreshing, problem, onRetry }: {
  d: MarketDashboard; visible: boolean; refreshing: boolean; problem: ScanProblem | null; onRetry: () => void;
}) {
  const [allWarnings, setAllWarnings] = useState(false);
  const updated = istTime(d.run_at);
  const c = d.counts;
  const count = (k: string) => (typeof c[k] === "number" ? (c[k] as number) : null);
  const parts: string[] = [];
  if (count("cash") != null) parts.push(`All NSE stocks ${count("cash")!.toLocaleString("en-IN")}`);
  if (count("fno") != null) parts.push(`F&O ${count("fno")!.toLocaleString("en-IN")}`);
  if (count("nifty50") != null) parts.push(`Nifty 50 ${count("nifty50")!.toLocaleString("en-IN")}`);
  if (count("no_today_bar")) parts.push(`${count("no_today_bar")!.toLocaleString("en-IN")} without today’s candle (left out)`);
  const warnings = d.warnings;
  const shownWarnings = allWarnings ? warnings : warnings.slice(0, 3);
  const sources = Object.entries(d.sources).filter((e): e is [string, string] => typeof e[1] === "string" && e[1].trim() !== "");
  return (
    <header data-testid="sd-head" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "6px 12px" }}>
        <h3 className="m-0" style={{ fontFamily: "var(--display)", fontSize: 20, fontWeight: 400, color: "var(--cp-ink)" }}>Scan dashboard</h3>
        <LiveChip open={d.market.open} visible={visible} seconds={d.market.refresh_seconds} />
        {updated && (
          <span data-testid="sd-updated" className="cp-mono-note">
            Updated {updated} IST{refreshing ? " · refreshing…" : ""}
          </span>
        )}
      </div>
      <p data-testid="sd-basis" className="m-0" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{d.basis.text}</p>
      {parts.length > 0 && <p data-testid="sd-counts" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{parts.join(" · ")}</p>}
      {problem && (
        <p data-testid="sd-refresh-problem" data-code={problem.code} role="status" className="m-0" style={{ fontSize: 12.5, color: "var(--amber)" }}>
          The last refresh failed ({problem.message}); the answer of {updated ?? "earlier"} is still shown.{" "}
          <button type="button" onClick={onRetry} style={{ border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", color: "var(--mint)" }}>Retry</button>
        </p>
      )}
      {warnings.length > 0 && (
        <div data-testid="sd-warnings" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)" }}>
          <ul className="m-0" style={{ paddingLeft: 18 }}>
            {shownWarnings.map((w, i) => <li key={`${i}-${w}`} data-testid="sd-warning">{w}</li>)}
          </ul>
          {warnings.length > 3 && (
            <button type="button" data-testid="sd-warnings-toggle" onClick={() => setAllWarnings((v) => !v)}
              style={{ border: 0, background: "none", padding: "2px 0 0 18px", cursor: "pointer", font: "inherit", fontSize: 12, color: "var(--mint)" }}>
              {allWarnings ? "Show fewer" : `+${warnings.length - 3} more`}
            </button>
          )}
        </div>
      )}
      {sources.length > 0 && (
        <details data-testid="sd-sources" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          <summary style={{ cursor: "pointer" }}>Where the numbers come from</summary>
          <ul className="m-0" style={{ paddingLeft: 18, paddingTop: 4 }}>
            {sources.map(([k, v]) => <li key={k}><span style={{ textTransform: "capitalize" }}>{k.replace(/_/g, " ")}</span>: {v}</li>)}
          </ul>
        </details>
      )}
    </header>
  );
}

// ── one widget ───────────────────────────────────────────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = { partial: "Partial", pending: "Pending", not_computed: "Not computed", error: "Unavailable" };

function Criteria({ items }: { items: DashboardCriterion[] }) {
  if (!items.length) return null;
  return (
    <ul data-testid="sd-criteria" aria-label="Criteria" className="m-0"
      style={{ listStyle: "none", padding: "8px 14px", borderTop: "1px solid var(--cp-line)", fontFamily: "var(--mono)", fontSize: 11.5, lineHeight: 1.55 }}>
      {items.map((c, i) => {
        const note = c.note ? (/^not applied/i.test(c.note) ? c.note : `not applied — ${c.note}`) : "not applied";
        return (
          <li key={i} data-testid="sd-criterion" data-applied={c.applied ? "true" : "false"} style={{ paddingLeft: Math.min(c.level, 6) * 14 }}>
            <span style={{ color: c.applied ? "var(--cp-ink-2)" : "var(--cp-ink-3)", opacity: c.applied ? 1 : 0.7 }}>{c.text}</span>
            {!c.applied && <span data-testid="sd-criterion-note" style={{ color: "var(--amber)" }}> · {note}</span>}
            {c.applied && c.note && <span style={{ color: "var(--cp-ink-3)" }}> · {c.note}</span>}
          </li>
        );
      })}
    </ul>
  );
}

type Sort = { col: number; dir: "asc" | "desc" } | null;

function compareCells(a: DashboardCell | undefined, b: DashboardCell | undefined): number {
  const am = a === null || a === undefined || a === "", bm = b === null || b === undefined || b === "";
  if (am && bm) return 0;
  if (am) return 1;
  if (bm) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "number") return -1;            // numbers before text ("n/a") in either direction
  if (typeof b === "number") return 1;
  return String(a).localeCompare(String(b));
}

function WidgetCard({ w, chartHref, onOpenSymbol }: { w: DashboardWidget; chartHref: (s: string) => string; onOpenSymbol: (s: string) => void }) {
  const [sort, setSort] = useState<Sort>(null);
  const rows = useMemo(() => {
    if (!sort) return w.rows;
    const sign = sort.dir === "asc" ? 1 : -1;
    return [...w.rows].sort((x, y) => {
      const a = x[sort.col], b = y[sort.col];
      const missA = a === null || a === undefined || a === "", missB = b === null || b === undefined || b === "";
      if (missA || missB) return compareCells(a, b);          // missing last, either direction
      return sign * compareCells(a, b);
    });
  }, [w.rows, sort]);
  const firstPct = w.columns.findIndex((c) => c.format === "pct");
  const symbols = w.row_kind === "symbol";
  const count = typeof w.count === "number" ? w.count : w.rows.length;
  // A widget that could not be computed shows why, never an empty table that would read as "nothing passes".
  const tableless = w.status === "pending" || w.status === "not_computed" || w.status === "error";
  const badge = STATUS_LABEL[w.status];
  const asOf = asOfText(w.as_of);

  const onHead = (i: number, col: DashboardColumn) => setSort((s) => {
    if (s?.col === i) return { col: i, dir: s.dir === "desc" ? "asc" : "desc" };
    return { col: i, dir: col.format === "text" ? "asc" : "desc" };
  });

  return (
    <section data-testid={`sd-widget-${w.id}`} data-status={w.status} data-row-kind={w.row_kind} aria-label={w.title} className="cp-card flex min-w-0 flex-col" style={{ padding: 0, overflow: "hidden" }}>
      <header className="flex min-w-0 flex-col" style={{ gap: 3, padding: "12px 14px 8px" }}>
        <div className="flex min-w-0 items-start" style={{ gap: 8 }}>
          <h4 data-testid="sd-widget-title" className="m-0" style={{ flex: "1 1 auto", minWidth: 0, fontSize: 14.5, fontWeight: 600, lineHeight: 1.3, color: "var(--cp-ink)" }}>{w.title}</h4>
          {badge && (
            <span data-testid="sd-widget-status" className="cp-pill" style={{ flex: "none", fontSize: 11, color: w.status === "partial" ? "var(--amber)" : "var(--cp-ink-2)" }}>{badge}</span>
          )}
          {symbols && !tableless && (
            <span data-testid="sd-widget-count" className="cp-pill" style={{ flex: "none", fontFamily: "var(--mono)", fontSize: 11 }}>{plural(count, "stock", "stocks")}</span>
          )}
        </div>
        <span className="cp-mono-note" data-testid="sd-widget-meta">
          {[w.universe, asOf ? `as of ${asOf}` : null].filter(Boolean).join(" · ")}
        </span>
      </header>
      <Criteria items={w.criteria} />
      {(tableless || w.note) && (
        <p data-testid="sd-widget-note" className="m-0" style={{ padding: "8px 14px", borderTop: "1px solid var(--cp-line)", fontSize: 12.5, lineHeight: 1.5, color: tableless || w.status !== "partial" ? "var(--cp-ink-2)" : "var(--amber)" }}>
          {w.note ?? (w.status === "pending" ? "Waiting for data; this widget fills in on a later refresh." : w.status === "error" ? "Not available right now; it retries on the next refresh." : "Not computed.")}
        </p>
      )}
      {!tableless && (rows.length === 0 ? (
        <p data-testid="sd-widget-empty" className="m-0" style={{ padding: "12px 14px", borderTop: "1px solid var(--cp-line)", fontSize: 13, color: "var(--cp-ink-2)" }}>
          {symbols ? "No stock passes right now." : "No data right now."}
        </p>
      ) : (
        <div className="cp-scroll" style={{ maxHeight: 340, overflow: "auto", borderTop: "1px solid var(--cp-line)" }}>
          <table data-testid="sd-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <caption className="sr-only">{w.title}</caption>
            <thead>
              <tr>
                {w.columns.map((col, i) => {
                  const on = sort?.col === i;
                  return (
                    <th key={col.key} scope="col" aria-sort={on ? (sort!.dir === "asc" ? "ascending" : "descending") : "none"} style={{ ...th, textAlign: i === 0 ? "left" : "right" }}>
                      <button type="button" data-testid={`sd-sort-${col.key}`} onClick={() => onHead(i, col)}
                        style={{ border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", letterSpacing: "inherit", textTransform: "inherit", color: on ? "var(--cp-ink)" : "inherit" }}>
                        {col.label}{on ? (sort!.dir === "asc" ? " ↑" : " ↓") : ""}
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => {
                const first = r[0];
                const sym = symbols && typeof first === "string" ? first : null;
                return (
                  <tr key={`${String(first)}-${ri}`} data-testid="sd-row" data-key={String(first ?? "")} style={{ borderTop: "1px solid var(--cp-line)" }}>
                    {w.columns.map((col, i) => {
                      const v = r[i];
                      if (i === 0) {
                        return (
                          <td key={col.key} style={{ ...td, textAlign: "left" }}>
                            {sym ? (
                              <a data-testid="sd-sym" data-symbol={sym} href={chartHref(sym)} title={`Open ${sym} in Chart Analysis`}
                                onClick={(e: MouseEvent<HTMLAnchorElement>) => {
                                  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;   // a new tab: let the link do it
                                  e.preventDefault();
                                  onOpenSymbol(sym);
                                }}
                                style={{ color: "var(--mint)", fontFamily: "var(--mono)", fontSize: 13, textDecoration: "none" }}>
                                {sym} <span aria-hidden>↗</span>
                              </a>
                            ) : <span style={{ color: "var(--cp-ink)" }}>{cellText(v, "text")}</span>}
                          </td>
                        );
                      }
                      const tone = i === firstPct && typeof v === "number" && Number.isFinite(v) ? (v < 0 ? "var(--cp-danger)" : "var(--mint)") : "var(--cp-ink)";
                      return <td key={col.key} className="cp-num" style={{ ...td, textAlign: "right", color: tone }}>{cellText(v, col.format)}</td>;
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  );
}

const th: CSSProperties = {
  position: "sticky", top: 0, zIndex: 1, background: "var(--bg-2)", padding: "8px 12px", fontFamily: "var(--mono)", fontSize: 10.5, fontWeight: 500,
  letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--cp-ink-3)", whiteSpace: "nowrap", borderBottom: "1px solid var(--cp-line)",
};
const td: CSSProperties = { padding: "8px 12px", whiteSpace: "nowrap" };
