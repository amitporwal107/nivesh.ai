/**
 * Scan Builder — the Result view: the matching stocks (a sortable table), where the numbers come from (the basis line and the
 * sources), how many stocks were looked at and left out, and the live chip of the 10-second refresh.
 */
import { Fragment, useMemo, useState, type CSSProperties } from "react";
import { EmptyBlock, ErrorBlock, LoadingBlock, fmtNum, fmtPct, signTone, TONE_COLOR } from "../../../../../components/ui";
import type { RunResult, ScanProblem } from "./scan-builder-data";

export type LiveState = "live" | "paused_hidden" | "closed" | "off" | "waiting";

const DASH = "—";
const inFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

function fmtVolume(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e7) return `${(v / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${(v / 1e5).toFixed(2)} L`;
  return fmtNum(v, 0);
}

export function fmtCell(v: number | null | undefined, format: string): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  if (format === "pct") return fmtPct(v, { signed: true, digits: 2 });
  if (format === "price") return inFmt.format(v);
  if (format === "volume") return fmtVolume(v);
  return Math.abs(v) >= 1000 ? fmtNum(v, 0) : String(Math.round(v * 100) / 100);
}

const istTime = (iso: string | null | undefined) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
};

function LiveChip({ state, seconds }: { state: LiveState; seconds: number }) {
  const text = {
    live: `Live · refreshes every ${seconds} s`,
    waiting: "Live · waiting to refresh",
    paused_hidden: "Paused · this tab is hidden",
    closed: "Market closed · not refreshing",
    off: "Not refreshing",
  }[state];
  const tone = state === "live" || state === "waiting" ? "mint" : "ink";
  return (
    <span data-testid="sb-live-chip" data-state={state} className="cp-pill" data-tone={tone === "mint" ? "mint" : undefined}>
      {(state === "live" || state === "waiting") && <span aria-hidden style={{ width: 6, height: 6, borderRadius: 999, background: "var(--mint)" }} className={state === "live" ? "cp-running" : undefined} />}
      {text}
    </span>
  );
}

type SortKey = { col: number | "symbol"; dir: "asc" | "desc" } | null;

export function ResultView({ result, problem, pending, firstRun, live, onRetry, onOpenSymbol }: {
  result: RunResult | null | undefined;
  problem: ScanProblem | null;
  pending: boolean;
  firstRun: boolean;
  live: LiveState;
  onRetry: () => void;
  onOpenSymbol?: (symbol: string) => void;
}) {
  const [sort, setSort] = useState<SortKey>(null);
  const rows = useMemo(() => {
    if (!result) return [];
    const r = result.rows.map((row, i) => ({ ...row, rank: i + 1 }));
    if (!sort) return r;
    const k = sort.col;
    const sign = sort.dir === "asc" ? 1 : -1;
    return [...r].sort((a, b) => {
      if (k === "symbol") return sign * a.symbol.localeCompare(b.symbol);
      const x = a.values[k], y = b.values[k];
      if (x == null && y == null) return 0;
      if (x == null) return 1;                   // missing last, either direction
      if (y == null) return -1;
      return sign * (x - y);
    });
  }, [result, sort]);

  if (!result && pending) {
    return (
      <div data-testid="sb-result-loading">
        <LoadingBlock label="Running the scan" rows={5} />
        {firstRun && <p className="m-0" style={{ paddingTop: 8, fontSize: 12.5, color: "var(--cp-ink-3)" }}>The first run of the day loads the market’s history on the server and can take up to a minute.</p>}
      </div>
    );
  }
  if (problem && !result) return <ProblemBlock problem={problem} onRetry={onRetry} />;
  if (!result) {
    return <EmptyBlock title="Run the scan to see the stocks that pass it." body="Press Run below. Every number is computed on our own data: NSE end-of-day bars with today’s Kite quotes, and fundamentals from our data platform." />;
  }

  const c = result.counts;
  const head = (label: string, key: number | "symbol", align: "left" | "right", testId: string) => {
    const on = sort?.col === key;
    const aria = on ? (sort?.dir === "asc" ? "ascending" : "descending") : "none";
    return (
      <th scope="col" aria-sort={aria} style={{ ...th, textAlign: align }}>
        <button type="button" data-testid={testId} onClick={() => setSort((s) => (s?.col === key ? (s.dir === "desc" ? { col: key, dir: "asc" } : null) : { col: key, dir: "desc" }))}
          style={{ border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", color: on ? "var(--cp-ink)" : "inherit", letterSpacing: "inherit", textTransform: "inherit" }}>
          {label}{on ? (sort?.dir === "asc" ? " ↑" : " ↓") : ""}
        </button>
      </th>
    );
  };
  const left: string[] = [];
  if (c.no_today_bar) left.push(`${c.no_today_bar.toLocaleString("en-IN")} without today’s candle`);
  if (c.no_history) left.push(`${c.no_history.toLocaleString("en-IN")} without enough data to decide`);
  const ranAt = istTime(result.run_at);

  return (
    <div data-testid="sb-result" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 12px" }}>
        <LiveChip state={live} seconds={result.market.refresh_seconds} />
        {ranAt && <span className="cp-mono-note" data-testid="sb-ran-at">Ran {ranAt} IST{result.elapsed_ms != null ? ` · ${Math.round(result.elapsed_ms)} ms` : ""}{pending ? " · refreshing…" : ""}</span>}
      </div>
      <p data-testid="sb-basis" className="m-0" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{result.basis.text}</p>
      {result.sources && (
        <p data-testid="sb-sources" className="m-0" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          {[result.sources.prices && `Prices: ${result.sources.prices}`, result.sources.today && `Today: ${result.sources.today}`, result.sources.fundamentals && `Fundamentals: ${result.sources.fundamentals}`].filter(Boolean).join(" · ")}
        </p>
      )}
      <p data-testid="sb-counts" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
        {result.universe.label}: {c.universe.toLocaleString("en-IN")} · evaluated {c.evaluated.toLocaleString("en-IN")} · <strong style={{ color: "var(--cp-ink)" }}>matched {c.matched.toLocaleString("en-IN")}</strong>
        {c.shown < c.matched ? ` · showing the first ${c.shown.toLocaleString("en-IN")}` : ""}
        {left.length ? ` · left out: ${left.join(", ")}` : ""}
      </p>
      {result.warnings.length > 0 && (
        <ul data-testid="sb-warnings" className="m-0" style={{ paddingLeft: 18, fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)" }}>
          {result.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
      {problem && <ProblemBlock problem={problem} onRetry={onRetry} />}
      {rows.length === 0 ? (
        <div data-testid="sb-result-empty" className="cp-card" style={{ padding: 16, fontSize: 13, color: "var(--cp-ink-2)" }}>No stock passes this scan right now.</div>
      ) : (
        <div className="cp-card cp-scroll overflow-x-auto" style={{ padding: 0 }}>
          <table data-testid="sb-result-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 320 + result.columns.length * 110 }}>
            <caption className="sr-only">Stocks that pass the scan</caption>
            <thead>
              <tr>
                <th scope="col" style={{ ...th, width: 36 }}>#</th>
                {head("Symbol", "symbol", "left", "sb-sort-symbol")}
                <th scope="col" style={th}>Name</th>
                {result.columns.map((col, i) => <Fragment key={col.id}>{head(col.alias, i, "right", `sb-sort-${col.id}`)}</Fragment>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} data-testid="sb-result-row" data-symbol={r.symbol} style={{ borderTop: "1px solid var(--cp-line)" }}>
                  <td style={{ ...td, color: "var(--cp-ink-3)" }} className="cp-num">{r.rank}</td>
                  <td style={td}>
                    {onOpenSymbol ? (
                      <button type="button" data-testid={`sb-sym-${r.symbol}`} onClick={() => onOpenSymbol(r.symbol)} title={`Open ${r.symbol} in Chart Analysis`}
                        style={{ border: 0, background: "none", padding: 0, cursor: "pointer", color: "var(--mint)", fontFamily: "var(--mono)", fontSize: 13 }}>{r.symbol}</button>
                    ) : <span className="cp-num">{r.symbol}</span>}
                    {r.today && r.today !== "live" && result.basis.mode === "live" && <span className="cp-mono-note" style={{ marginLeft: 6 }}>{r.today}</span>}
                  </td>
                  <td style={{ ...td, color: "var(--cp-ink-2)", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis" }}>{r.name ?? DASH}</td>
                  {result.columns.map((col, i) => {
                    const v = r.values[i];
                    const color = col.format === "pct" && v != null ? TONE_COLOR[signTone(v)] : "var(--cp-ink)";
                    return <td key={col.id} className="cp-num" style={{ ...td, textAlign: "right", color }}>{fmtCell(v, col.format)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ProblemBlock({ problem, onRetry }: { problem: ScanProblem; onRetry: () => void }) {
  if (problem.code === "invalid_spec") {
    return (
      <div data-testid="sb-error" data-code={problem.code} role="alert" className="cp-card" style={{ padding: "12px 16px", borderColor: "var(--danger-line)", fontSize: 13, lineHeight: 1.5 }}>
        <strong style={{ color: "var(--cp-danger)" }}>The scan has a problem:</strong> {problem.message}
        {problem.path && <span data-testid="sb-error-path" className="cp-mono-note" style={{ marginLeft: 8 }}>at {problem.path}</span>}
      </div>
    );
  }
  if (problem.code === "run_too_soon") {
    return (
      <div data-testid="sb-error" data-code={problem.code} role="status" className="cp-card" style={{ padding: "12px 16px", fontSize: 13 }}>
        Runs are limited to one every few seconds. {problem.retryAfter ? `Try again in ${Math.ceil(problem.retryAfter)} s.` : "Try again shortly."}
      </div>
    );
  }
  const title = problem.code === "data_unavailable" ? "The market data could not be loaded for this run"
    : problem.code === "feature_disabled" ? "The Scan Builder is not enabled for your account"
      : "The scan did not run";
  return (
    <div data-testid="sb-error" data-code={problem.code}>
      <ErrorBlock title={title} error={problem.message} onRetry={problem.code === "feature_disabled" ? undefined : onRetry} />
    </div>
  );
}

const th: CSSProperties = { padding: "9px 12px", textAlign: "left", fontFamily: "var(--mono)", fontSize: 10.5, fontWeight: 500, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--cp-ink-3)", whiteSpace: "nowrap" };
const td: CSSProperties = { padding: "9px 12px", whiteSpace: "nowrap" };
