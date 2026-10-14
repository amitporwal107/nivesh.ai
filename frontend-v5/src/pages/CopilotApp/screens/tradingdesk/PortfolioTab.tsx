/**
 * Smart trading desk — 05 Portfolio & risk. Design-spec §7 (desktop) and §11
 * M5 (phone). Brokers are read only, and nothing places an order; the only
 * writes are the user's own simulated paper trades and price alerts.
 *
 * Card "Portfolio · broker hub" (left)
 *   sources line           GET /api/broker/accounts                        (useBrokerAccounts)
 *   value, P&L, positions  GET /api/portfolio/holdings-enriched            (useHoldingsEnriched); positions are the
 *                          direct stocks (asset type equity / stock), each weight the route's share of the whole portfolio
 *   donut and legend       GET /api/portfolio/market-cap-split             (useMarketCapSplit): direct stocks by NSE index
 *                          membership, what the route cannot split yet, and the funds it leaves out; cash is not read
 *   risk checks (7)        overall risk, volatility, beta, VaR and drivers  GET /api/portfolio/risk-analytics (useRiskAnalytics)
 *                          position concentration                           holdings-enriched (largest weight vs 25%)
 *                          sector concentration                             GET /api/portfolio/exposure/concentration
 *                          correlated positions                             GET /api/portfolio/correlation?sessions=120&limit=10
 *                          gap risk, liquidity                              no source: shown as "—" with the reason
 * Card "Paper trades · predicted vs actual" (right)
 *   tiles and calibration  GET /api/paper-trades/evaluation?sample=&portfolio=P5-NEXT (usePaperEvaluation): the move-odds
 *                          model's own paper portfolio, the selected five a session; 403 = not enabled
 *   open today, last 5     GET /api/desk/paper-trades?status=all          (usePaperTrades): your desk paper trades
 * Then the broker block (desk/BrokerPositions: live holdings and F&O positions per account)
 *                          GET /api/broker/accounts, /api/portfolio/holdings, /api/broker/positions
 * Then your full paper-trade and alert lists (PaperDesk.tsx): close and delete live there
 *                          GET /api/desk/paper-trades, POST …/{id}/close, GET /api/desk/alerts, DELETE …/{id}
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import { useHoldingsEnriched, usePortfolioConcentration } from "@/hooks/use-portfolio";
import type { PaperSample } from "@/services/adapters/paperTrades.adapter";
import { BrokerIcon, StockIcon } from "../../components/EntityIcon";
import {
  Btn, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone,
  type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { fmtStamp } from "../desk/broker";
import { BrokerPositions } from "../desk/BrokerPositions";
import { lensOf, readConcentration } from "../portfolio/concentration-data";
import { loadError } from "../portfolio/data";
import { QueryProblem, fmtDay, fmtPrice } from "../trading/parts";
import { useBrokerAccounts, usePaperEvaluation } from "../trading/queries";
import { BUCKET_LABEL, SETUP_BUCKETS, type SetupBucket } from "./desk-data";
import { heldDays, openedToday, tradeR, tradeReturnPct, usePaperTrades, type PaperTrade } from "./desk-trading";
import { AlertsBlock, PaperTradesBlock } from "./PaperDesk";
import {
  CORR_SESSIONS, SINGLE_STOCK_LIMIT_PCT, calibrationRows, capDonut, largestStock, readPortfolio, recordTiles, useCorrelation,
  useMarketCapSplit, useRiskAnalytics,
  type CalibrationRow, type CorrPair, type DonutKey, type PortfolioView, type RiskAnalytics, type StockPosition,
} from "./portfolio-data";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;
const line = "1px solid var(--cp-line)";
const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;
const eyebrow = (size = 10, color = "var(--cp-ink-3)"): CSSProperties => ({ fontFamily: "var(--mono)", fontSize: size, letterSpacing: "0.16em", textTransform: "uppercase", color });

/** Flag a pair at or above this when the route does not send its own threshold. */
const CORR_HIGH_DEFAULT = 0.7;

// ── frame ────────────────────────────────────────────────────────────────

/** A desktop module card: header bar (eyebrow left, meta right, bg-0) and a padded body. */
function ModuleCard({ title, pill, meta, testId, children, bodyGap = 16 }: { title: ReactNode; pill?: ReactNode; meta?: ReactNode; testId: string; children: ReactNode; bodyGap?: number }) {
  return (
    <section data-testid={testId} className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden", boxShadow: "var(--shadow-card)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 10px", padding: "13px 18px", borderBottom: line, background: "var(--bg-0)" }}>
        <span data-testid={`${testId}-title`} className="cp-eyebrow">{title}</span>
        {pill}
        {meta && <span className="cp-eyebrow" style={{ marginLeft: "auto", color: "var(--cp-ink-4)" }}>{meta}</span>}
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: bodyGap, padding: "16px 18px" }}>{children}</div>
    </section>
  );
}

/** A phone card (design-spec §11: radius 14, bg-1, line): an eyebrow head and the body. */
function PhoneCard({ title, aside, testId, children }: { title: ReactNode; aside?: ReactNode; testId: string; children: ReactNode }) {
  return (
    <section data-testid={testId} className="cp-card flex min-w-0 flex-col" style={{ gap: 12, padding: "14px 14px 16px" }}>
      <div className="flex items-center justify-between" style={{ gap: 8 }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span data-testid={`${testId}-title`} className="cp-eyebrow">{title}</span>
        </span>
        {aside}
      </div>
      {children}
    </section>
  );
}

function ReadOnlyPill() {
  return <span data-testid="desk-portfolio-readonly" className="cp-pill" data-tone="indigo">Read-only</span>;
}

function Head({ children, tone }: { children: ReactNode; tone?: string }) {
  return <span style={{ ...eyebrow(9.5, tone ?? "var(--cp-ink-3)") }}>{children}</span>;
}

/** Segmented control (design-spec §1, small): bg-2 track, ON bg-4 + ink. */
function Segmented<T extends string>({ label, value, options, onChange, testId }: { label: string; value: T; options: Array<{ value: T; label: string }>; onChange: (v: T) => void; testId: string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex" style={{ gap: 2, padding: 2, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            data-testid={`${testId}-${o.value}`}
            onClick={() => onChange(o.value)}
            style={{
              padding: "5px 10px", borderRadius: 999, border: 0, cursor: "pointer", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase",
              background: on ? "var(--bg-4)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// ── broker line ──────────────────────────────────────────────────────────

function useBrokerLine(): { names: string[]; last: string | null; state: "loading" | "error" | "none" | "ready" } {
  const q = useBrokerAccounts();
  if (q.isPending) return { names: [], last: null, state: "loading" };
  if (q.isError) return { names: [], last: null, state: "error" };
  if (!q.data.length) return { names: [], last: null, state: "none" };
  const stamps = q.data.flatMap((a) => (a.lastSyncAt && Number.isFinite(new Date(a.lastSyncAt).getTime()) ? [a.lastSyncAt] : []));
  const last = stamps.sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0] ?? null;
  return { names: q.data.map((a) => a.name), last, state: "ready" };
}

/** "ZERODHA · LAST READ 12 OCT, 3:42 PM" with the brokers' icons; `withTime` false gives the names only (phone). */
function SourcesLine({ withTime = true }: { withTime?: boolean }) {
  const b = useBrokerLine();
  const text =
    b.state === "loading" ? "Checking broker connections"
    : b.state === "error" ? "Broker connections didn’t load"
    : b.state === "none" ? "No broker connected · holdings on record in Nivesh"
    : withTime ? `${b.names.join(" · ")} · ${b.last ? `last read ${fmtStamp(b.last)}` : "nothing read yet"}`
    : b.names.join(" · ");
  return (
    <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
      {b.state === "ready" && <span className="flex items-center" style={{ gap: 3 }}>{b.names.map((n) => <BrokerIcon key={n} name={n} size={16} />)}</span>}
      <span data-testid="desk-portfolio-sources" style={{ ...eyebrow(10), letterSpacing: "0.12em", lineHeight: 1.6 }}>{text}</span>
    </span>
  );
}

function ValueLine({ view, size }: { view: PortfolioView; size: number }) {
  return (
    <div className="flex flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
      <span data-testid="desk-portfolio-value" className="cp-num" style={{ fontFamily: "var(--display)", fontSize: size, letterSpacing: "-0.03em", lineHeight: 1.05, color: "var(--cp-ink)" }}>
        {fmtINR(view.totalValueRs, { compact: true })}
      </span>
      <span data-testid="desk-portfolio-pnl" className="cp-num" title="Total P&L on what you paid" style={{ fontSize: 12, color: TONE_COLOR[signTone(view.totalPnlRs)] }}>
        {fmtINR(view.totalPnlRs, { compact: true, signed: true })} · {fmtPct(view.totalPnlPct, { signed: true })}
      </span>
    </div>
  );
}

// ── donut by market cap ──────────────────────────────────────────────────

// Categorical slots (validated for adjacent-pair colour-vision separation in light and dark).
// Light values sit under 3:1 on white, so every slice is also listed with its figure.
const RING_STYLE = `.desk-ring{--ring-1:#2a78d6;--ring-2:#eb6834;--ring-3:#1baf7a;--ring-4:#eda100;--ring-5:#e87ba4}
:root[data-theme="dark"] .desk-ring{--ring-1:#3987e5;--ring-2:#d95926;--ring-3:#199e70;--ring-4:#c98500;--ring-5:#d55181}`;

const DONUT_COLOR: Record<DonutKey, string> = {
  large: "var(--ring-1)",
  mid: "var(--ring-2)",
  small: "var(--ring-3)",
  micro: "var(--ring-4)",
  unclassified: "var(--ink-5)",
  unsplit: "var(--ink-5)",
  funds: "var(--ring-5)",
};

const DONUT_LABEL: Record<DonutKey, string> = {
  large: "Large cap",
  mid: "Mid cap",
  small: "Small cap",
  micro: "Micro cap",
  unclassified: "Unclassified",
  unsplit: "Not split yet",
  funds: "Funds & other",
};

function Donut({ slices, size, r, stroke, count }: { slices: Array<{ key: DonutKey; pct: number }>; size: number; r: number; stroke: number; count: number }) {
  const c = 2 * Math.PI * r;
  const total = slices.reduce((s, x) => s + x.pct, 0) || 1;
  const gap = slices.length > 1 ? 3 : 0;
  let start = 0;
  return (
    <svg
      data-testid="desk-portfolio-donut"
      viewBox={`0 0 ${size} ${size}`}
      width={size}
      height={size}
      role="img"
      aria-label={`Portfolio by market cap: ${slices.map((s) => `${DONUT_LABEL[s.key]} ${fmtPct(s.pct)}`).join(", ")}`}
      style={{ flex: "none" }}
    >
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg-3)" strokeWidth={stroke} />
      {slices.map((s) => {
        const full = (s.pct / total) * c;
        const len = Math.max(0.5, full - gap);
        const el = (
          <circle
            key={s.key}
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={DONUT_COLOR[s.key]}
            strokeWidth={stroke}
            strokeDasharray={`${len} ${c - len}`}
            strokeDashoffset={-start}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          >
            <title>{`${DONUT_LABEL[s.key]}: ${fmtPct(s.pct)}`}</title>
          </circle>
        );
        start += full;
        return el;
      })}
      <text data-testid="desk-portfolio-donut-count" x={size / 2} y={size / 2 + 4} textAnchor="middle" style={{ fontFamily: "var(--display)", fontSize: 28, fill: "var(--cp-ink)" }}>{fmtNum(count)}</text>
      <text x={size / 2} y={size / 2 + 18} textAnchor="middle" style={{ fontFamily: "var(--mono)", fontSize: 8, letterSpacing: "0.14em", fill: "var(--cp-ink-3)" }}>{count === 1 ? "STOCK" : "STOCKS"}</text>
    </svg>
  );
}

interface LegendRow {
  key: DonutKey | "cash";
  label: string;
  pct: number | null;
  valueRs: number | null;
  available: boolean;
  /** Why the row has no figure. */
  why?: string;
}

function CapSplit({ view, size }: { view: PortfolioView; size: number }) {
  const q = useMarketCapSplit();
  const stocks = view.stocks.length;
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading the market-cap split" rows={2} />;
  else if (q.isError) body = <div data-testid="desk-mcap-error"><QueryProblem what="The market-cap split" error={q.error} onRetry={() => q.refetch()} /></div>;
  else {
    const d = q.data;
    const donut = capDonut(d);
    if (!donut) {
      body = <span data-testid="desk-mcap-empty" style={quiet}>No holdings to split by market cap.</span>;
    } else {
      const byKey = new Map(donut.slices.map((s) => [s.key, s]));
      const rows: LegendRow[] = [];
      for (const b of ["large", "mid", "small", "micro", "unclassified"] as const) {
        const sl = d.slices.find((x) => x.bucket === b);
        const drawn = byKey.get(b);
        if ((b === "micro" || b === "unclassified") && !drawn) continue;
        rows.push({
          key: b, label: DONUT_LABEL[b], pct: drawn?.pct ?? (sl?.available ? 0 : null), valueRs: drawn?.valueRs ?? (sl?.available ? 0 : null),
          available: !!sl?.available, why: sl && !sl.available ? sl.reason ?? "Not on record yet" : undefined,
        });
      }
      const u = byKey.get("unsplit");
      if (u) rows.push({ key: "unsplit", label: DONUT_LABEL.unsplit, pct: u.pct, valueRs: u.valueRs, available: true, why: d.unsplit?.reason ?? undefined });
      const f = byKey.get("funds");
      if (f) rows.push({ key: "funds", label: DONUT_LABEL.funds, pct: f.pct, valueRs: f.valueRs, available: true });
      rows.push({ key: "cash", label: "Cash", pct: null, valueRs: null, available: false, why: "Broker cash balances are not read" });
      const reason = d.unsplit?.reason ?? (!d.available ? d.reason : null);
      body = (
        <div className="flex flex-col" style={{ gap: 10 }}>
          <div className="desk-ring flex flex-wrap items-center" style={{ gap: "12px 18px" }}>
            <style>{RING_STYLE}</style>
            <Donut slices={donut.slices} size={size} r={size === 120 ? 46 : 43} stroke={size === 120 ? 12 : 11} count={stocks} />
            <ul className="m-0 flex flex-col" style={{ flex: "1 1 150px", minWidth: 0, gap: 7, padding: 0, listStyle: "none" }}>
              {rows.map((r) => (
                <li key={r.key} data-testid="desk-mcap-row" data-bucket={r.key} data-available={r.available ? "true" : "false"} data-value={r.valueRs ?? ""} title={r.why ?? (r.valueRs != null ? `${r.label}: ${fmtINR(r.valueRs, { compact: true })}` : undefined)} className="flex items-center" style={{ gap: 8, fontSize: 12.5, minWidth: 0 }}>
                  <span aria-hidden="true" style={{ flex: "none", width: 8, height: 8, borderRadius: 999, background: r.available && r.key !== "cash" ? DONUT_COLOR[r.key as DonutKey] : "transparent", border: r.available ? 0 : "1px dashed var(--line-3)" }} />
                  <span style={{ flex: "1 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--cp-ink-2)" }}>{r.label}</span>
                  <span data-testid="desk-mcap-weight" className="cp-num" style={{ flex: "none", minWidth: 44, textAlign: "right", color: r.pct == null ? "var(--cp-ink-4)" : "var(--cp-ink)" }}>{r.pct == null ? "—" : fmtPct(r.pct)}</span>
                </li>
              ))}
            </ul>
          </div>
          <span data-testid="desk-mcap-note" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            Shares of the <span data-testid="desk-mcap-total" className="cp-num">{fmtINR(donut.totalRs, { compact: true })}</span> the route valued. Large = Nifty 100, mid = Nifty Midcap 150, small = Nifty Smallcap 250 (NSE index lists{d.asOf ? `, ${fmtDay(d.asOf)}` : ""}). Broker cash balances are not read.
            {reason && <> <span data-testid="desk-mcap-reason" style={{ color: "var(--amber)" }}>{reason}.</span></>}
          </span>
        </div>
      );
    }
  }
  return <div data-testid="desk-portfolio-mcap" className="flex min-w-0 flex-col" style={{ gap: 8 }}>{body}</div>;
}

// ── positions ────────────────────────────────────────────────────────────

const SHOWN = 8;

function Positions({ view, phone }: { view: PortfolioView; phone: boolean }) {
  const [all, setAll] = useState(false);
  const stocks = view.stocks;
  if (!stocks.length) {
    return (
      <span data-testid="desk-portfolio-no-stocks" style={quiet}>
        No direct stocks on record. Your {plural(view.holdingsCount, "holding")} are funds or other assets.
      </span>
    );
  }
  const cols = phone ? "minmax(0,1fr) 72px 64px 46px" : "minmax(0,1fr) 78px 64px 44px";
  const rows = all ? stocks : stocks.slice(0, SHOWN);
  const cell: CSSProperties = { textAlign: "right", whiteSpace: "nowrap" };
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <div role="table" aria-label="Positions" data-testid="desk-portfolio-positions-table" className="flex min-w-0 flex-col">
        <div role="row" className="grid" style={{ gridTemplateColumns: cols, gap: 8, paddingBottom: 6, borderBottom: line }}>
          {["Stock", "Value ₹", "P&L", "Weight"].map((h, i) => (
            <span key={h} role="columnheader" style={{ ...eyebrow(8.5, "var(--cp-ink-4)"), letterSpacing: "0.12em", textAlign: i ? "right" : "left" }}>{h}</span>
          ))}
        </div>
        {rows.map((s: StockPosition) => {
          const over = s.weightPct != null && s.weightPct > SINGLE_STOCK_LIMIT_PCT;
          const sym = s.symbol ?? s.name;
          return (
            <div key={s.id} role="row" data-testid="desk-portfolio-position" data-symbol={sym} className="grid items-center" style={{ gridTemplateColumns: cols, gap: 8, padding: "8px 0", borderBottom: line, fontSize: 12.5 }}>
              <span role="cell" className="flex min-w-0 items-center" style={{ gap: 7 }} title={s.name}>
                <StockIcon symbol={sym} name={s.name} size={18} />
                <span className="cp-num" style={{ fontSize: 12, fontWeight: 500, color: "var(--cp-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sym}</span>
              </span>
              <span role="cell" className="cp-num" style={{ ...cell, color: "var(--cp-ink-2)" }}>{fmtINR(s.valueRs, { compact: true })}</span>
              <span role="cell" data-testid="desk-portfolio-pnl-pct" className="cp-num" style={{ ...cell, color: TONE_COLOR[signTone(s.pnlPct)] }}>{fmtPct(s.pnlPct, { signed: true })}</span>
              <span role="cell" className="cp-num" style={cell}>
                <span data-testid="desk-portfolio-weight" data-over={over ? "true" : "false"} title={over ? `Above the ${SINGLE_STOCK_LIMIT_PCT}% single-stock limit` : undefined} style={{ color: over ? "var(--amber)" : "var(--cp-ink-2)", fontWeight: over ? 600 : undefined }}>
                  {fmtPct(s.weightPct, { digits: phone ? 0 : 1 })}
                </span>
              </span>
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
        <span style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          Weight = share of the whole portfolio; above {SINGLE_STOCK_LIMIT_PCT}% is amber (the single-stock limit).
        </span>
        {stocks.length > SHOWN && (
          <Btn variant="ghost" data-testid="desk-portfolio-show-all" aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? "Show fewer" : `Show all ${fmtNum(stocks.length)}`}
          </Btn>
        )}
      </div>
    </div>
  );
}

// ── risk checks (7 rows, design-spec §7 / M5) ────────────────────────────

/** Levels and the 5-segment bar: a known level fills 2–5 segments; no figure fills none. */
type Level = "low" | "medium" | "high" | "very_high";
const LEVEL: Record<Level, { label: string; segments: number; tone: Tone }> = {
  low: { label: "Low", segments: 2, tone: "mint" },
  medium: { label: "Medium", segments: 3, tone: "amber" },
  high: { label: "High", segments: 4, tone: "danger" },
  very_high: { label: "Very high", segments: 5, tone: "danger" },
};
const RATING_LEVEL: Record<string, Level> = { LOW: "low", MEDIUM: "medium", HIGH: "high", VERY_HIGH: "very_high" };
const IMPACT_TONE: Record<string, Tone> = { LOW: "mint", MEDIUM: "amber", HIGH: "danger" };

interface Check {
  id: string;
  label: string;
  detail: ReactNode;
  /** The figure at the right ("High", "30.0%", "1 pair", "—"). */
  value: string;
  level: Level | null;
  /** The word under the bar on a phone; the level's own label unless the check says otherwise. */
  levelText?: string;
  more?: ReactNode;
}

function corrSummary(pairs: CorrPair[], flagged: number, high: number): string {
  return flagged > 0 ? `${plural(flagged, "pair")} ≥ ${fmtNum(high, 2)}` : pairs.length ? `None ≥ ${fmtNum(high, 2)}` : "—";
}

function PairRow({ p, high }: { p: CorrPair; high: number }) {
  const flagged = p.corr >= high;
  const weights = [
    p.weightA != null && p.weightB != null ? `${fmtPct(p.weightA)} and ${fmtPct(p.weightB)} of the portfolio` : "",
    p.commonSessions != null ? `${fmtNum(p.commonSessions)} common sessions` : "",
  ].filter(Boolean).join(" · ") || null;
  return (
    <li data-testid="desk-corr-pair" data-pair={`${p.a}-${p.b}`} data-high={flagged ? "true" : "false"} className="grid items-center" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "2px 12px", padding: "7px 0", borderTop: line }}>
      <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px", fontSize: 12.5 }}>
        <span className="inline-flex items-center" style={{ gap: 5 }}><StockIcon symbol={p.a} size={16} /><span data-testid="desk-corr-a" className="cp-num" style={{ color: "var(--cp-ink)" }}>{p.a}</span></span>
        <span aria-hidden="true" style={{ color: "var(--cp-ink-4)" }}>↔</span>
        <span className="inline-flex items-center" style={{ gap: 5 }}><StockIcon symbol={p.b} size={16} /><span data-testid="desk-corr-b" className="cp-num" style={{ color: "var(--cp-ink)" }}>{p.b}</span></span>
      </span>
      <span className="flex items-center justify-end" style={{ gap: 8 }}>
        {flagged && <span data-testid="desk-corr-flag" className="cp-pill" data-tone="amber">High</span>}
        <span data-testid="desk-corr-value" className="cp-num" style={{ fontSize: 13, color: flagged ? "var(--amber)" : "var(--cp-ink)" }}>{fmtNum(p.corr, 2)}</span>
      </span>
      {weights && <span style={{ gridColumn: "1 / -1", fontSize: 11, color: "var(--cp-ink-3)" }}>{weights}</span>}
    </li>
  );
}

function riskDetail(r: RiskAnalytics): ReactNode {
  const parts: ReactNode[] = [];
  if (r.score != null) parts.push(<span key="s">Rated from 1-year volatility, score {fmtNum(r.score, 1)} of 10</span>);
  if (r.beta != null) parts.push(<span key="b">beta <span data-testid="desk-risk-beta-value" className="cp-num">{fmtNum(r.beta, 2)}</span> vs Nifty 50</span>);
  if (r.var1dRs != null || r.var1dPct != null) {
    parts.push(
      <span key="v">1-day VaR <span data-testid="desk-risk-var-value" className="cp-num">{fmtINR(r.var1dRs)}{r.var1dPct != null ? ` (${fmtPct(r.var1dPct, { digits: 2 })})` : ""}</span> at {fmtNum(r.varConfidencePct ?? 95)}% confidence</span>,
    );
  }
  if (!parts.length) return "No volatility, beta or value-at-risk figure on record for these holdings";
  return parts.map((p, i) => <span key={i}>{i ? " · " : ""}{p}</span>);
}

function useRiskChecks(view: PortfolioView): { checks: Check[]; overall: Level | null; risk: ReturnType<typeof useRiskAnalytics> } {
  const risk = useRiskAnalytics();
  const conc = usePortfolioConcentration();
  const corr = useCorrelation();
  const r = risk.data && !risk.data.empty ? risk.data : null;
  const overall = r?.rating ? RATING_LEVEL[r.rating] ?? null : null;
  const checks: Check[] = [];

  // 1 · Overall risk — the route's rating, from the portfolio's 1-year volatility.
  checks.push({
    id: "overall",
    label: "Overall risk",
    value: overall ? LEVEL[overall].label : "—",
    level: overall,
    detail: risk.isPending ? "Loading the risk figures" : risk.isError ? "The risk figures didn’t load" : r ? riskDetail(r) : "No holdings with a risk figure",
    more: r && r.drivers.length > 0 ? (
      <ul className="m-0 flex flex-col" style={{ gap: 4, padding: 0, listStyle: "none" }}>
        {r.drivers.map((dr) => (
          <li key={dr.type} data-testid={`desk-risk-driver-${dr.type.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`} data-level={dr.impact ? titleLevel(dr.impact) : "—"} className="flex items-center justify-between" style={{ gap: 10, fontSize: 12 }}>
            <span style={{ color: "var(--cp-ink-2)" }}>{dr.label} · {dr.pct != null ? `${fmtPct(dr.pct)} of the portfolio’s value` : "no share sent"}</span>
            <span className="cp-num" style={{ fontSize: 11, color: TONE_COLOR[dr.impact ? IMPACT_TONE[dr.impact] ?? "ink" : "ink"] }}>{dr.impact ? titleLevel(dr.impact) : "—"}</span>
          </li>
        ))}
        {r.coveragePct != null && <li style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>These figures cover {fmtPct(r.coveragePct)} of the portfolio’s value: the holdings with a figure on record.</li>}
      </ul>
    ) : undefined,
  });

  // 2 · Position concentration — the largest single stock against the 25% limit.
  const top = largestStock(view.stocks);
  if (top) {
    const over = top.weightPct > SINGLE_STOCK_LIMIT_PCT;
    checks.push({
      id: "position",
      label: "Position concentration",
      value: fmtPct(top.weightPct),
      level: over ? "high" : "low",
      levelText: over ? "Above limit" : "Within limit",
      detail: (
        <>
          <span className="inline-flex items-center" style={{ gap: 4, verticalAlign: "middle" }}><StockIcon symbol={top.symbol ?? top.name} name={top.name} size={14} />{top.symbol ?? top.name}</span>
          {" "}is <span data-testid="desk-risk-single-stock-value" className="cp-num">{fmtPct(top.weightPct)}</span> of the portfolio · limit {SINGLE_STOCK_LIMIT_PCT}%
        </>
      ),
    });
  } else {
    checks.push({ id: "position", label: "Position concentration", value: "—", level: null, detail: "No direct stock with a weight on record" });
  }

  // 3 · Sector concentration — the largest classified sector, the route's verdict, HHI and effective sectors.
  const lens = conc.data && !conc.data.empty ? lensOf(readConcentration(conc.data), "sector") : null;
  const largest = lens?.items.find((i) => !i.isResidual && i.pct != null) ?? null;
  if (lens && largest?.pct != null) {
    const verdict = lens.verdict;
    const level: Level | null = verdict === "balanced" ? "low" : verdict === "elevated" ? "medium" : verdict === "over-concentrated" ? "high" : null;
    const parts = [`${largest.name} is ${fmtPct(largest.pct)} of sector exposure${lens.capPct != null ? `, ${largest.pct > lens.capPct ? "above" : "under"} the ${fmtNum(lens.capPct)}% cap` : ""}`];
    if (lens.hhi != null) parts.push(`HHI ${fmtNum(lens.hhi)}`);
    if (lens.effectiveN != null) parts.push(`${fmtNum(lens.effectiveN, 1)} effective sectors`);
    checks.push({
      id: "sector",
      label: "Sector concentration",
      value: fmtPct(largest.pct),
      level,
      levelText: verdict === "balanced" ? "Balanced" : verdict === "elevated" ? "Elevated" : verdict === "over-concentrated" ? "Over-concentrated" : "—",
      detail: parts.join(" · "),
    });
  } else {
    checks.push({
      id: "sector", label: "Sector concentration", value: "—", level: null,
      detail: conc.isPending ? "Loading the sector split" : conc.isError ? "The sector split didn’t load" : "No classified sector on record",
    });
  }

  // 4 · Correlated positions — pairs at or above the route's threshold, over 120 sessions of daily returns.
  if (corr.data) {
    const d = corr.data;
    const high = d.highThreshold ?? CORR_HIGH_DEFAULT;
    const flagged = d.highPairs ?? d.pairs.filter((p) => p.corr >= high).length;
    const top2 = d.pairs[0];
    checks.push({
      id: "correlation",
      label: "Correlated positions",
      value: d.pairs.length ? (flagged > 0 ? plural(flagged, "pair") : "None") : "—",
      level: d.pairs.length ? (flagged > 0 ? "high" : "low") : null,
      levelText: d.pairs.length ? corrSummary(d.pairs, flagged, high) : "—",
      detail: d.pairs.length
        ? <span data-testid="desk-corr-summary">{top2 ? `${top2.a} ↔ ${top2.b} ${fmtNum(top2.corr, 2)}` : ""}{d.avgCorr != null ? ` · average ${fmtNum(d.avgCorr, 2)}` : ""}{d.pairsTotal != null ? ` of ${plural(d.pairsTotal, "pair")}` : ""} · {fmtNum(d.sessions ?? CORR_SESSIONS)} sessions</span>
        : <span data-testid="desk-corr-none">Fewer than two of your stocks have enough daily prices to compare{d.sessions ? ` over ${fmtNum(d.sessions)} sessions` : ""}.</span>,
      more: (
        <div className="flex flex-col" style={{ gap: 6 }}>
          {d.pairs.length > 0 && <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>{d.pairs.map((p) => <PairRow key={`${p.a}-${p.b}`} p={p} high={high} />)}</ul>}
          {d.skipped.length > 0 && (
            <span data-testid="desk-corr-skipped" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
              Not compared: {d.skipped.map((s) => `${s.symbol}${s.reason ? ` (${s.reason})` : ""}`).join("; ")}.
            </span>
          )}
          <span data-testid="desk-corr-method" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            {d.method ?? "Correlation of daily returns"} over {fmtNum(d.sessions ?? CORR_SESSIONS)} sessions{d.minSessions != null ? ` (a stock needs at least ${fmtNum(d.minSessions)})` : ""}{d.source ? ` · ${d.source}` : ""}{d.asOf ? ` · end of day ${fmtDay(d.asOf)}` : ""}. A pair at {fmtNum(high, 2)} or above is flagged.
          </span>
        </div>
      ),
    });
  } else {
    checks.push({
      id: "correlation", label: "Correlated positions", value: "—", level: null,
      detail: corr.isPending ? "Working out which holdings move together" : (
        <span data-testid="desk-corr-error" className="inline-flex flex-wrap items-center" style={{ gap: 8 }}>
          Correlated positions didn’t load
          <button type="button" onClick={() => corr.refetch()} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", color: "var(--mint)", fontSize: 11.5 }}>Retry ›</button>
        </span>
      ),
    });
  }

  // 5 · Gap risk — no overnight-gap measure exists for holdings.
  checks.push({ id: "gap", label: "Gap risk", value: "—", level: null, detail: "No overnight-gap figure is on record for these holdings" });

  // 6 · Volatility — the route has 1-year volatility only (the design's 1-month figure has no source).
  checks.push({
    id: "volatility",
    label: "Volatility · 1Y",
    value: r?.volatilityPct != null ? fmtPct(r.volatilityPct) : "—",
    level: r?.volatilityPct != null ? overall : null,
    detail: r?.volatilityPct != null
      ? <><span data-testid="desk-risk-volatility-value" className="cp-num">{fmtPct(r.volatilityPct)}</span> a year · value-weighted 1-year volatility of the holdings with a figure</>
      : "No 1-year volatility on record for these holdings",
  });

  // 7 · Liquidity — no traded-value figure exists for holdings.
  checks.push({ id: "liquidity", label: "Liquidity", value: "—", level: null, detail: "No traded-value figure is on record for these holdings" });

  return { checks, overall, risk };
}

function titleLevel(impact: string): string {
  const k = impact.toUpperCase();
  return k === "LOW" ? "Low" : k === "MEDIUM" ? "Medium" : k === "HIGH" ? "High" : impact;
}

function levelColor(level: Level | null): string {
  return level ? TONE_COLOR[LEVEL[level].tone] : "var(--cp-ink-4)";
}

function LevelBar({ level }: { level: Level | null }) {
  const filled = level ? LEVEL[level].segments : 0;
  return (
    <span data-testid="desk-risk-bar" data-filled={filled} aria-hidden="true" className="inline-flex" style={{ gap: 2 }}>
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i} style={{ width: 9, height: 5, borderRadius: 1.5, background: i < filled ? levelColor(level) : "var(--bg-3)" }} />
      ))}
    </span>
  );
}

function CheckRow({ c, phone }: { c: Check; phone: boolean }) {
  const [open, setOpen] = useState(false);
  const levelText = c.levelText ?? (c.level ? LEVEL[c.level].label : "—");
  return (
    <li
      data-testid={`desk-risk-${c.id}`}
      data-level={c.level ?? "none"}
      data-value={c.value}
      className="flex flex-col"
      style={{ gap: 6, padding: "9px 0", borderTop: line }}
    >
      <div className="grid items-start" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "2px 12px" }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--cp-ink)" }}>{c.label}</span>
          <span style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{c.detail}</span>
        </span>
        {phone ? (
          <span className="flex flex-col items-end" style={{ gap: 4, paddingTop: 3 }}>
            <LevelBar level={c.level} />
            <span data-testid="desk-risk-level" className="cp-num" style={{ fontSize: 9.5, letterSpacing: "0.06em", textTransform: "uppercase", color: levelColor(c.level), whiteSpace: "nowrap" }}>{levelText}</span>
          </span>
        ) : (
          <span data-testid="desk-risk-value" className="cp-num" title={levelText} style={{ fontSize: 12, paddingTop: 1, textAlign: "right", color: levelColor(c.level), whiteSpace: "nowrap" }}>{c.value}</span>
        )}
      </div>
      {c.more && (
        <>
          <button
            type="button"
            data-testid={`desk-risk-${c.id}-toggle`}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="self-start"
            style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 11.5, color: "var(--mint)", fontFamily: "var(--sans)" }}
          >
            {open ? "Hide details" : "Details ›"}
          </button>
          {open && <div data-testid={`desk-risk-${c.id}-more`}>{c.more}</div>}
        </>
      )}
    </li>
  );
}

function RiskList({ view, phone }: { view: PortfolioView; phone: boolean }) {
  const { checks, risk } = useRiskChecks(view);
  return (
    <div className="flex min-w-0 flex-col">
      <ul data-testid="desk-risk-list" className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
        {checks.map((c) => <CheckRow key={c.id} c={c} phone={phone} />)}
      </ul>
      {risk.isError && <QueryProblem what="Beta, volatility and value at risk" error={risk.error} onRetry={() => risk.refetch()} />}
      <span data-testid="desk-portfolio-risk-note" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)", paddingTop: 8, borderTop: line }}>
        Overall risk is the route’s rating from 1-year volatility (under 10% low, under 18% medium, under 28% high, then very high). Volatility · 1Y: no 1-month figure exists. Gap risk and liquidity have no source yet.
      </span>
    </div>
  );
}

// ── desktop: left card ───────────────────────────────────────────────────

function useHoldingsView() {
  const q = useHoldingsEnriched();
  return { q, view: q.data ? readPortfolio(q.data) : null };
}

function EmptyHoldings() {
  const { go } = useCopilotShell();
  return (
    <div data-testid="desk-portfolio-empty">
      <EmptyBlock
        title="No holdings on record yet"
        body="Connect a broker account (read-only) or import a statement, and your positions, market-cap split and risk checks show here."
        action={<Btn variant="primary" data-testid="desk-portfolio-connect" onClick={() => go("page/brokers")}>Connect or import your portfolio</Btn>}
      />
    </div>
  );
}

function HubCard() {
  const { q, view } = useHoldingsView();
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading your holdings" rows={4} />;
  else if (q.isError || !view) body = <ErrorBlock title="Your holdings didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  else if (view.holdingsCount === 0) body = <EmptyHoldings />;
  else {
    body = (
      <>
        <div className="flex flex-col" style={{ gap: 6 }}>
          <SourcesLine />
          <ValueLine view={view} size={34} />
        </div>
        <CapSplit view={view} size={120} />
        <div data-testid="desk-portfolio-positions" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
          <div className="flex flex-wrap items-baseline justify-between" style={{ gap: 8 }}>
            <Head>Positions</Head>
            <span style={{ ...eyebrow(9.5, "var(--cp-ink-4)") }}><span data-testid="desk-portfolio-stock-count">{fmtNum(view.stocks.length)}</span> direct {view.stocks.length === 1 ? "stock" : "stocks"}</span>
          </div>
          <Positions view={view} phone={false} />
        </div>
        <div data-testid="desk-portfolio-risk" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <Head>Risk checks · linked holdings</Head>
          <RiskList view={view} phone={false} />
        </div>
      </>
    );
  }
  return (
    <ModuleCard title="Portfolio · broker hub" pill={<ReadOnlyPill />} testId="desk-portfolio-hub">
      {body}
    </ModuleCard>
  );
}

// ── right card: paper trades, predicted vs actual ────────────────────────

const SAMPLE_NOTE: Record<PaperSample, string> = {
  forward: "Forward sample: sessions recorded as they happened, after the model was frozen.",
  replay: "Replay sample: the frozen model run over 2025 sessions after the fact; not live.",
};

function Tile({ k, v, s, testId, tone }: { k: string; v: ReactNode; s: ReactNode; testId: string; tone?: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 3, padding: "11px 12px", borderRadius: 10, background: "var(--bg-2)", border: line }}>
      <span style={{ ...eyebrow(9.5) }}>{k}</span>
      <span data-testid={testId} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 22, letterSpacing: "-0.02em", color: tone ?? "var(--cp-ink)" }}>{v}</span>
      <span style={{ fontSize: 11.5, lineHeight: 1.4, color: "var(--cp-ink-3)" }}>{s}</span>
    </div>
  );
}

function Calibration({ rows }: { rows: CalibrationRow[] }) {
  const scale = Math.max(10, Math.ceil(Math.max(...rows.flatMap((r) => [r.predictedPct, r.realisedPct])) / 10) * 10);
  const at = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;
  return (
    <div data-testid="desk-calibration" className="flex flex-col" style={{ gap: 9 }}>
      {rows.map((r) => {
        const band = `${fmtNum(r.loPct)}–${fmtNum(r.hiPct)}%`;
        return (
          <div key={r.loPct} data-testid="desk-calibration-row" data-lo={Math.round(r.loPct)} className="flex flex-col" style={{ gap: 4 }}>
            <div className="flex items-baseline justify-between" style={{ gap: 8 }}>
              <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-2)" }}>{band}</span>
              <span className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-3)" }}>
                <span data-testid="desk-calibration-predicted">{fmtPct(r.predictedPct, { digits: 0 })}</span> → <span data-testid="desk-calibration-realised" style={{ color: "var(--mint)" }}>{fmtPct(r.realisedPct, { digits: 0 })}</span> · n {fmtNum(r.n)}
              </span>
            </div>
            <span role="img" aria-label={`Predicted ${band}: model ${fmtPct(r.predictedPct)}, actual ${fmtPct(r.realisedPct)}, ${plural(r.n, "prediction")}`} className="flex flex-col" style={{ gap: 2 }}>
              <span style={{ display: "block", height: 5, borderRadius: 999, background: "var(--bg-3)" }}><span style={{ display: "block", height: 5, width: at(r.predictedPct), borderRadius: 999, background: "var(--ink-5)" }} /></span>
              <span style={{ display: "block", height: 5, borderRadius: 999, background: "var(--bg-3)" }}><span style={{ display: "block", height: 5, width: at(r.realisedPct), borderRadius: 999, background: "var(--mint)" }} /></span>
            </span>
          </div>
        );
      })}
      <span className="flex flex-wrap" style={{ gap: "2px 14px", fontSize: 10.5, color: "var(--cp-ink-3)" }}>
        <span className="inline-flex items-center" style={{ gap: 5 }}><span aria-hidden="true" style={{ width: 12, height: 5, borderRadius: 999, background: "var(--ink-5)" }} />Predicted · model average</span>
        <span className="inline-flex items-center" style={{ gap: 5 }}><span aria-hidden="true" style={{ width: 12, height: 5, borderRadius: 999, background: "var(--mint)" }} />Actual · how often it happened</span>
        <span className="cp-num">scale 0–{fmtNum(scale)}%</span>
      </span>
    </div>
  );
}

function ModelRecord() {
  const [sample, setSample] = useState<PaperSample>("forward");
  const q = usePaperEvaluation(sample, "P5-NEXT");
  const switcher = (
    <Segmented<PaperSample>
      label="Sample"
      testId="desk-paper-sample"
      value={sample}
      onChange={setSample}
      options={[{ value: "forward", label: "Forward" }, { value: "replay", label: "Replay · 2025" }]}
    />
  );
  let body: ReactNode;
  if (q.data?.kind === "no_access") {
    body = (
      <div data-testid="desk-paper-no-access" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)", padding: "10px 12px", borderRadius: 10, border: "1px dashed var(--line-3)" }}>
        The model’s paper-trade record is not enabled for this account. It is limited to invited accounts; an admin can turn on the move-odds research feature.
      </div>
    );
  } else if (q.isPending) body = <LoadingBlock label="Loading the model’s evaluation" rows={3} />;
  else if (q.isError) body = <ErrorBlock title="The model’s evaluation didn’t load" error={q.error} onRetry={() => q.refetch()} />;
  else if (q.data.kind === "error") body = <ErrorBlock title="The model’s evaluation didn’t load" error={q.data.message} onRetry={() => q.refetch()} />;
  else if (q.data.kind !== "ok") {
    body = <span data-testid="desk-paper-empty" style={quiet}>No evaluation of the {sample} sample is stored yet. The engine stores one after each run.</span>;
  } else {
    const ev = q.data.data;
    const t = recordTiles(ev.buckets.selected);
    const head = ev.modes.find((m) => m.mode === ev.headline_mode) ?? ev.modes.find((m) => m.headline) ?? null;
    const net = head?.net_mean != null ? head.net_mean * 100 : null;
    const rows = calibrationRows(ev.buckets.selected);
    const none = "No outcomes yet";
    body = (
      <div className="flex flex-col" style={{ gap: 12 }}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
          <Tile k="Predicted" testId="desk-record-predicted" v={fmtPct(t.predictedPct)} s={t.n ? `Average model probability · n ${fmtNum(t.n)}` : none} />
          <Tile k="Realised" testId="desk-record-realised" v={fmtPct(t.realisedPct)} tone={t.realisedPct != null ? "var(--mint)" : undefined} s={t.n ? "High reached +5% the next session" : none} />
          <Tile
            k="Net after costs"
            testId="desk-record-net"
            v={net == null ? "—" : fmtPct(net, { signed: true, digits: 2 })}
            tone={net == null ? undefined : TONE_COLOR[signTone(net)]}
            s={net == null ? none : `Average per trade after ${fmtNum(ev.costs.base, 2)}% costs · ${fmtNum(head?.closed_trades ?? 0)} trades`}
          />
          <Tile k="False positives" testId="desk-record-false" v={t.misses == null ? "—" : fmtNum(t.misses)} s={t.n ? `Selected, but no +5% move · of ${fmtNum(t.n)}` : none} />
        </div>
        <span data-testid="desk-paper-statement" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {ev.statement.text}{/counted session/i.test(ev.statement.text) ? "" : ` ${plural(ev.sessions.counted, "counted session")}; the pre-registered minimum is ${fmtNum(ev.statement.min_sessions)}.`}
        </span>
        <div className="flex flex-col" style={{ gap: 8 }}>
          <Head>Calibration</Head>
          {rows.length ? <Calibration rows={rows} /> : <span data-testid="desk-calibration-none" style={quiet}>No probability bucket has a selected trade with an outcome yet in the {sample} sample.</span>}
        </div>
        <span style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          P5-NEXT: the move-odds model’s probability that a stock’s high reaches +5% in the next session, over the five it selects each session.
          {q.data.asOf ? ` Latest evaluation stored for the session of ${fmtDay(q.data.asOf)}.` : ""}
        </span>
      </div>
    );
  }
  return (
    <div data-testid="desk-paper" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
        <Head>The model’s paper trades · P5-NEXT</Head>
        {switcher}
      </div>
      <span data-testid="desk-paper-sample-note" style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{SAMPLE_NOTE[sample]}</span>
      {body}
    </div>
  );
}

const isBucket = (b: string | null | undefined): b is SetupBucket => !!b && (SETUP_BUCKETS as readonly string[]).includes(b);
function setupOf(t: PaperTrade): string {
  const b = t.source?.bucket;
  if (isBucket(b)) return BUCKET_LABEL[b];
  return t.source?.kind === "scanner" ? "Scanner setup" : "Setup not recorded";
}
const NO_P = "No model probability is stored with a desk paper trade";

function YourTrades() {
  const q = usePaperTrades();
  if (q.isPending) return <LoadingBlock label="Loading your paper trades" rows={2} />;
  if (q.isError) return <div data-testid="desk-paper-card-error"><QueryProblem what="Your paper trades" error={q.error} onRetry={() => q.refetch()} /></div>;
  const open = q.data.trades.filter((t) => t.status === "open");
  const today = open.filter((t) => openedToday(t));
  const closed = q.data.trades.filter((t) => t.status === "closed").slice(0, 5);
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 14 }}>
      <div data-testid="desk-paper-today" className="flex flex-col" style={{ gap: 6 }}>
        <Head tone="var(--mint)">Open · added today</Head>
        {today.length === 0 ? (
          <span data-testid="desk-paper-today-none" style={quiet}>
            No paper trade added today{open.length ? ` · ${plural(open.length, "open trade")} in all, listed below` : ""}.
          </span>
        ) : (
          <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
            {today.map((t) => (
              <li key={t.id} data-testid="desk-paper-today-row" data-id={t.id} className="grid items-center" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "2px 10px", padding: "7px 0", borderTop: line }}>
                <span className="flex min-w-0 items-center" style={{ gap: 6, fontSize: 12.5 }}>
                  <StockIcon symbol={t.symbol} size={16} />
                  <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{t.symbol}</span>
                  <span style={{ color: "var(--cp-ink-3)" }}>· {fmtNum(t.quantity)}</span>
                </span>
                <span data-testid="desk-paper-today-p" className="cp-pill" title={NO_P} style={{ fontSize: 9, padding: "2px 7px" }}>P —</span>
                <span data-testid="desk-paper-today-levels" className="cp-num" style={{ gridColumn: "1 / -1", fontSize: 11, color: "var(--cp-ink-3)" }}>
                  Entry {fmtPrice(t.entry)} · Stop {fmtPrice(t.stop)} · Target {t.target != null ? fmtPrice(t.target) : "none"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div data-testid="desk-paper-last5" className="flex flex-col" style={{ gap: 6 }}>
        <Head>Last 5 closed</Head>
        {closed.length === 0 ? (
          <span data-testid="desk-paper-last5-none" style={quiet}>No closed paper trades yet.</span>
        ) : (
          <div role="table" aria-label="Last 5 closed paper trades" className="flex flex-col">
            <div role="row" className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 40px 84px 48px", gap: 8, paddingBottom: 5 }}>
              {["Trade", "P", "Outcome", "R"].map((h, i) => (
                <span key={h} role="columnheader" style={{ ...eyebrow(8.5, "var(--cp-ink-4)"), letterSpacing: "0.12em", textAlign: i ? "right" : "left" }}>{h}</span>
              ))}
            </div>
            {closed.map((t) => {
              const ret = tradeReturnPct(t);
              const r = tradeR(t);
              const days = heldDays(t);
              const reason = t.exitReason === "target" ? "target" : t.exitReason === "stop" ? "stop" : t.exitReason === "manual" ? "closed by you" : null;
              return (
                <div key={t.id} role="row" data-testid="desk-paper-last5-row" data-id={t.id} className="grid items-center" style={{ gridTemplateColumns: "minmax(0,1fr) 40px 84px 48px", gap: 8, padding: "7px 0", borderTop: line }}>
                  <span role="cell" className="flex min-w-0 flex-col" style={{ gap: 1 }}>
                    <span className="flex items-center" style={{ gap: 6, fontSize: 12.5 }}>
                      <StockIcon symbol={t.symbol} size={16} />
                      <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{t.symbol}</span>
                    </span>
                    <span data-testid="desk-paper-last5-setup" style={{ fontSize: 11, lineHeight: 1.4, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
                      {setupOf(t)}{days != null ? ` · ${plural(days, "day")}` : ""}{reason ? ` · ${reason}` : ""}
                    </span>
                  </span>
                  <span role="cell" data-testid="desk-paper-last5-pred" className="cp-num" title={NO_P} style={{ textAlign: "right", fontSize: 11.5, color: "var(--cp-ink-4)" }}>—</span>
                  <span role="cell" data-testid="desk-paper-last5-outcome" className="cp-num" style={{ textAlign: "right", fontSize: 12, color: TONE_COLOR[signTone(ret)] }}>
                    {fmtPct(ret, { signed: true })}
                  </span>
                  <span role="cell" data-testid="desk-paper-last5-r" className="cp-num" style={{ textAlign: "right", fontSize: 12, color: TONE_COLOR[signTone(r)] }}>
                    {r == null ? "—" : `${r > 0 ? "+" : r < 0 ? "−" : ""}${fmtNum(Math.abs(r), 1)}R`}
                  </span>
                </div>
              );
            })}
          </div>
        )}
        <span style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          Your desk paper trades. P is not stored with a trade, so it shows “—”. Outcome = exit vs entry; R = (exit − entry) ÷ (entry − stop). Close trades and manage alerts in the lists below.
        </span>
      </div>
    </div>
  );
}

function PaperCard() {
  const q = usePaperTrades();
  const closed = q.data ? q.data.summary?.closed ?? q.data.trades.filter((t) => t.status === "closed").length : null;
  return (
    <ModuleCard
      title="Paper trades · predicted vs actual"
      testId="desk-portfolio-record"
      meta={<span data-testid="desk-paper-card-closed">{closed == null ? "—" : `${fmtNum(closed)} closed`}</span>}
    >
      <ModelRecord />
      <div style={{ borderTop: line, paddingTop: 14 }}>
        <YourTrades />
      </div>
    </ModuleCard>
  );
}

function PaperLists() {
  return (
    <ModuleCard title="Your paper trades and price alerts" pill={<span className="cp-pill" data-tone="amber">Simulated · no orders</span>} testId="desk-portfolio-paper">
      <PaperTradesBlock />
      <AlertsBlock />
    </ModuleCard>
  );
}

// ── phone (design-spec §11 M5) ───────────────────────────────────────────

function PhonePortfolio() {
  const { q, view } = useHoldingsView();
  const b = useBrokerLine();
  if (q.isPending) return <LoadingBlock label="Loading your holdings" rows={4} />;
  if (q.isError || !view) return <ErrorBlock title="Your holdings didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  const hub = (
    <PhoneCard testId="desk-portfolio-hub" title="Your portfolio" aside={<ReadOnlyPill />}>
      {view.holdingsCount === 0 ? <EmptyHoldings /> : (
        <>
          <SourcesLine withTime={false} />
          <ValueLine view={view} size={34} />
          <CapSplit view={view} size={112} />
        </>
      )}
    </PhoneCard>
  );
  if (view.holdingsCount === 0) return hub;
  return (
    <>
      {hub}
      <PhoneRisk view={view} />
      <PhoneCard
        testId="desk-portfolio-positions"
        title="Positions"
        aside={<span data-testid="desk-portfolio-synced" className="cp-mono-note" style={{ fontSize: 9 }}>{b.last ? `Last read ${fmtStamp(b.last)}` : b.state === "none" ? "No broker connected" : ""}</span>}
      >
        <Positions view={view} phone />
      </PhoneCard>
      <p data-testid="desk-portfolio-readonly-note" className="m-0" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        <span aria-hidden="true" style={{ color: "var(--cp-indigo)" }}>●</span> Read-only view from connected brokers. No trading or order execution in Nivesh.
      </p>
    </>
  );
}

function PhoneRisk({ view }: { view: PortfolioView }) {
  const { overall } = useRiskChecks(view);
  return (
    <PhoneCard
      testId="desk-portfolio-risk"
      title="Risk dashboard"
      aside={<span data-testid="desk-risk-overall-pill" className="cp-pill" data-tone={overall ? LEVEL[overall].tone : "ink"}>{overall ? `${LEVEL[overall].label} risk` : "Risk —"}</span>}
    >
      <RiskList view={view} phone />
    </PhoneCard>
  );
}

// ── tab ──────────────────────────────────────────────────────────────────

export default function PortfolioTab() {
  const { mobile } = useCopilotShell();
  if (mobile) {
    return (
      <div data-testid="desk-portfolio" data-layout="phone" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
        <PhonePortfolio />
        <PaperCard />
        <BrokerPositions />
        <PaperLists />
      </div>
    );
  }
  return (
    <div data-testid="desk-portfolio" data-layout="desktop" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <div className="grid items-start" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 16 }}>
        <HubCard />
        <PaperCard />
      </div>
      <BrokerPositions />
      <PaperLists />
      <Footnote>Holdings and risk figures are as Nivesh last valued them; broker connections are read-only and nothing here places an order.</Footnote>
    </div>
  );
}
