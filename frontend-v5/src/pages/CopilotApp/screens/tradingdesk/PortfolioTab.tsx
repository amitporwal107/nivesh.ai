/**
 * Smart trading desk — 05 Portfolio & risk. Design: "Smart Trading Desk",
 * Portfolio & risk. Brokers are read only, and nothing places an order; the
 * only writes are the user's own simulated paper trades and price alerts.
 *
 * Left card · Portfolio, broker hub
 *   sources line          GET /api/broker/accounts                        (useBrokerAccounts)
 *   value, P&L, positions GET /api/portfolio/holdings-enriched            (useHoldingsEnriched); the list is the
 *                         direct stocks (asset type equity / stock), each weight the route's share of the whole portfolio
 *   sector ring           GET /api/portfolio/exposure/concentration       (usePortfolioConcentration), sector.items
 *   market-cap split      GET /api/portfolio/market-cap-split             (useMarketCapSplit, portfolio-data.ts)
 *   risk checks           largest stock weight from holdings-enriched, sector concentration from the
 *                         concentration route, beta / volatility / 1-day VaR / risk drivers from
 *                         GET /api/portfolio/risk-analytics               (useRiskAnalytics, portfolio-data.ts)
 *   correlated positions  GET /api/portfolio/correlation?sessions=120&limit=10 (useCorrelation)
 * Right card · your trades and the model's record
 *   trade journal         GET /api/positional/journal/summary/portfolio   (useJournalSummary)
 *   calibration           GET /api/paper-trades/evaluation?sample=&portfolio=P5-NEXT (usePaperEvaluation);
 *                         forward and replay are separate samples, forward first; 403 = not enabled
 * Below: your paper trades and price alerts (PaperDesk.tsx)
 *                         GET /api/desk/paper-trades, POST …/{id}/close, GET /api/desk/alerts, DELETE …/{id}
 * Then the broker block (desk/BrokerPositions, as on the Trader desk)
 *                         GET /api/broker/accounts, /api/portfolio/holdings, /api/broker/positions
 */
import { useState, type ReactNode } from "react";
import { useHoldingsEnriched, usePortfolioConcentration } from "@/hooks/use-portfolio";
import type { PaperSample } from "@/services/adapters/paperTrades.adapter";
import { BrokerIcon, StockIcon, StockName } from "../../components/EntityIcon";
import {
  Btn, DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Pill,
  TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone,
  type Column, type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { fmtStamp } from "../desk/broker";
import { BrokerPositions } from "../desk/BrokerPositions";
import { VERDICT_META, lensOf, readConcentration } from "../portfolio/concentration-data";
import { loadError } from "../portfolio/data";
import { Choices, QueryProblem, fmtDay, fmtSigned } from "../trading/parts";
import { useBrokerAccounts, useJournalSummary, usePaperEvaluation } from "../trading/queries";
import { AlertsBlock, PaperTradesBlock } from "./PaperDesk";
import {
  CORR_SESSIONS, SINGLE_STOCK_LIMIT_PCT, calibrationRows, largestStock, readPortfolio, sectorSlices, useCorrelation, useMarketCapSplit,
  useRiskAnalytics,
  type CalibrationRow, type CapBucket, type CorrPair, type PortfolioView, type RiskAnalytics, type SectorSlice, type StockPosition,
} from "./portfolio-data";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;
const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;

/** A beta above this is marked high; below BETA_LOW, low. */
const BETA_HIGH = 1.2;
const BETA_LOW = 0.8;

/** Flag a pair at or above this when the route does not send its own threshold. */
const CORR_HIGH_DEFAULT = 0.7;

function Card({ title, pill, aside, testId, children }: { title: string; pill?: ReactNode; aside?: ReactNode; testId: string; children: ReactNode }) {
  return (
    <section data-testid={testId} className="cp-card flex flex-col min-w-0" style={{ gap: 18, padding: 16 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px" }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span className="cp-eyebrow">{title}</span>
          {pill}
        </span>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Sub({ title, note, children, testId }: { title: ReactNode; note?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} className="flex flex-col min-w-0" style={{ gap: 10 }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
        <span className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>{title}</span>
        {note && <span className="cp-mono-note">{note}</span>}
      </div>
      {children}
    </div>
  );
}

// ── sources ──────────────────────────────────────────────────────────────

function SourcesLine() {
  const q = useBrokerAccounts();
  const line = (text: string, icons?: ReactNode) => (
    <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
      {icons}
      <span data-testid="desk-portfolio-sources" className="cp-mono-note" style={{ lineHeight: 1.6 }}>{text}</span>
    </span>
  );
  if (q.isPending) return line("Checking broker connections");
  if (q.isError) return line("Broker connections didn’t load");
  if (!q.data.length) return line("No broker connected · holdings on record in Nivesh");
  const stamps = q.data.flatMap((a) => (a.lastSyncAt && Number.isFinite(new Date(a.lastSyncAt).getTime()) ? [a.lastSyncAt] : []));
  const last = stamps.sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0];
  return line(
    `${q.data.map((a) => a.name).join(" · ")} · ${last ? `last read ${fmtStamp(last)}` : "nothing read yet"}`,
    <span className="flex items-center" style={{ gap: 3 }}>{q.data.map((a) => <BrokerIcon key={a.id} name={a.name} size={16} />)}</span>,
  );
}

// ── sector ring ──────────────────────────────────────────────────────────

// Categorical slots (validated for adjacent-pair colour-vision separation in light and dark);
// "Other sectors" is neutral. Light values sit under 3:1 on white, so every slice is also listed with its figure.
const RING_STYLE = `.desk-ring{--ring-1:#2a78d6;--ring-2:#eb6834;--ring-3:#1baf7a;--ring-4:#eda100;--ring-5:#e87ba4}
:root[data-theme="dark"] .desk-ring{--ring-1:#3987e5;--ring-2:#d95926;--ring-3:#199e70;--ring-4:#c98500;--ring-5:#d55181}`;

const sliceColor = (s: SectorSlice, i: number) => (s.rest ? "var(--bg-4)" : `var(--ring-${i + 1})`);

function Ring({ slices }: { slices: SectorSlice[] }) {
  const size = 128;
  const r = 50;
  const c = 2 * Math.PI * r;
  const total = slices.reduce((s, x) => s + x.pct, 0) || 1;
  let start = 0;
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label={`Sector split: ${slices.map((s) => `${s.name} ${fmtPct(s.pct)}`).join(", ")}`} style={{ flex: "none" }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg-2)" strokeWidth={16} />
      {slices.map((s, i) => {
        const full = (s.pct / total) * c;
        const len = Math.max(0, full - (slices.length > 1 ? 2 : 0));
        const el = (
          <circle
            key={s.name}
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={sliceColor(s, i)}
            strokeWidth={16}
            strokeDasharray={`${len} ${c - len}`}
            strokeDashoffset={-start}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          >
            <title>{`${s.name}: ${fmtPct(s.pct)}`}</title>
          </circle>
        );
        start += full;
        return el;
      })}
      <text x={size / 2} y={size / 2 + 4} textAnchor="middle" style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.12em", fill: "var(--cp-ink-3)" }}>BY SECTOR</text>
    </svg>
  );
}

function SectorRing() {
  const q = usePortfolioConcentration();
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading the sector split" rows={2} />;
  else if (q.isError) body = <ErrorBlock title="The sector split didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  else {
    const split = q.data.empty ? null : sectorSlices(q.data);
    body = !split ? (
      <span data-testid="desk-portfolio-sectors-none" style={quiet}>No sector split is on record for these holdings yet.</span>
    ) : (
      <div className="desk-ring flex flex-wrap items-center" style={{ gap: "12px 20px" }}>
        <style>{RING_STYLE}</style>
        <Ring slices={split.slices} />
        <ul className="m-0 flex flex-col" style={{ flex: "1 1 180px", minWidth: 0, gap: 6, padding: 0, listStyle: "none" }}>
          {split.slices.map((s, i) => (
            <li key={s.name} data-testid="desk-portfolio-sector-row" className="flex items-center" style={{ gap: 8, fontSize: 12.5, minWidth: 0 }}>
              <span aria-hidden="true" style={{ flex: "none", width: 10, height: 10, borderRadius: 3, background: sliceColor(s, i) }} />
              <span style={{ flex: "1 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--cp-ink-2)" }}>{s.name}</span>
              <span className="cp-num" style={{ flex: "none", color: "var(--cp-ink)" }}>{fmtPct(s.pct)}</span>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <Sub title="Allocation" note="By sector" testId="desk-portfolio-sectors">
      {body}
      <span data-testid="desk-portfolio-sector-note" style={quiet}>
        Sector exposure of the whole portfolio, counting the stocks inside your funds where their holdings are on record. The market-cap split below covers direct stocks only.
      </span>
    </Sub>
  );
}

// ── market-cap split ─────────────────────────────────────────────────────

const CAP_LABEL: Record<CapBucket, { name: string; rule: string }> = {
  large: { name: "Large cap", rule: "Nifty 100" },
  mid: { name: "Mid cap", rule: "Nifty Midcap 150" },
  small: { name: "Small cap", rule: "Nifty Smallcap 250" },
  micro: { name: "Micro and other", rule: "rest of the Nifty Total Market" },
  unclassified: { name: "Unclassified", rule: "in none of these indices" },
};
const capColor = (b: CapBucket, i: number) => (b === "unclassified" ? "var(--bg-4)" : `var(--ring-${i + 1})`);

function CapSplitBlock() {
  const q = useMarketCapSplit();
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading the market-cap split" rows={2} />;
  else if (q.isError) body = <div data-testid="desk-mcap-error"><QueryProblem what="The market-cap split" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (q.data.slices.length === 0 || q.data.totalValueRs === 0) {
    body = <span data-testid="desk-mcap-empty" style={quiet}>No direct stocks to split by market cap.</span>;
  } else {
    const d = q.data;
    const u = d.unsplit;
    const large = d.slices.find((sl) => sl.bucket === "large");
    const unsplitLabel = large?.available ? "Outside Nifty 100 — not split yet" : "Not split yet";
    const drawn = d.slices.filter((sl) => sl.available && sl.weightPct != null && sl.weightPct > 0);
    const unsplitShare = u?.weightPct != null && u.weightPct > 0 ? u.weightPct : 0;
    const total = drawn.reduce((a, sl) => a + (sl.weightPct ?? 0), 0) + unsplitShare || 1;
    const reason = u?.reason ?? d.reason ?? d.slices.find((sl) => !sl.available && sl.reason)?.reason ?? null;
    body = (
      <div className="desk-ring flex flex-col" style={{ gap: 10 }}>
        <style>{RING_STYLE}</style>
        <div
          data-testid="desk-mcap-bar"
          role="img"
          aria-label={`By market cap: ${[...drawn.map((sl) => `${CAP_LABEL[sl.bucket].name} ${fmtPct(sl.weightPct)}`), ...(unsplitShare ? [`${unsplitLabel} ${fmtPct(unsplitShare)}`] : [])].join(", ")}`}
          className="flex overflow-hidden"
          style={{ height: 10, borderRadius: 5, background: "var(--bg-2)", gap: 2 }}
        >
          {drawn.map((sl) => (
            <span key={sl.bucket} title={`${CAP_LABEL[sl.bucket].name}: ${fmtPct(sl.weightPct)}`} style={{ width: `${((sl.weightPct ?? 0) / total) * 100}%`, background: capColor(sl.bucket, CAP_BUCKET_INDEX[sl.bucket]) }} />
          ))}
          {unsplitShare > 0 && (
            <span data-testid="desk-mcap-bar-unsplit" title={`${unsplitLabel}: ${fmtPct(unsplitShare)}`} style={{ width: `${(unsplitShare / total) * 100}%`, background: "repeating-linear-gradient(135deg, var(--bg-4) 0 4px, var(--bg-3) 4px 8px)" }} />
          )}
        </div>
        <ul className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
          {d.slices.map((sl) => (
            <li key={sl.bucket} data-testid="desk-mcap-row" data-bucket={sl.bucket} data-available={sl.available ? "true" : "false"} className="flex items-center" style={{ gap: 8, fontSize: 12.5, minWidth: 0 }}>
              <span aria-hidden="true" style={{ flex: "none", width: 10, height: 10, borderRadius: 3, background: sl.available ? capColor(sl.bucket, CAP_BUCKET_INDEX[sl.bucket]) : "transparent", border: sl.available ? 0 : "1px dashed var(--line-3)" }} />
              <span style={{ flex: "1 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--cp-ink-2)" }}>
                {CAP_LABEL[sl.bucket].name} <span style={{ color: "var(--cp-ink-3)" }}>· {CAP_LABEL[sl.bucket].rule}</span>
              </span>
              {sl.available ? (
                <>
                  <span data-testid="desk-mcap-count" className="cp-num" style={{ flex: "none", fontSize: 11, color: "var(--cp-ink-3)" }}>{sl.count != null ? plural(sl.count, "stock") : ""}</span>
                  <span data-testid="desk-mcap-value" className="cp-num" style={{ flex: "none", fontSize: 11, color: "var(--cp-ink-3)" }}>{fmtINR(sl.valueRs, { compact: true })}</span>
                  <span data-testid="desk-mcap-weight" className="cp-num" style={{ flex: "none", width: 48, textAlign: "right", color: "var(--cp-ink)" }}>{fmtPct(sl.weightPct)}</span>
                </>
              ) : (
                <span data-testid="desk-mcap-weight" className="cp-num" style={{ flex: "none", color: "var(--cp-ink-3)" }}>Not available</span>
              )}
            </li>
          ))}
        </ul>
        {u && (
          <div data-testid="desk-mcap-unsplit" role="status" className="flex flex-col" style={{ gap: 4, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
            <span style={{ fontSize: 12.5, color: "var(--cp-ink)" }}>
              {unsplitLabel}: <span data-testid="desk-mcap-unsplit-value" className="cp-num">{fmtINR(u.valueRs, { compact: true })} ({fmtPct(u.weightPct)})</span>
              {u.count != null ? ` · ${plural(u.count, "stock")}` : ""}
            </span>
            {reason && <span data-testid="desk-mcap-reason" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{reason}.</span>}
          </div>
        )}
        {!u && !d.available && reason && (
          <span data-testid="desk-mcap-reason" role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{reason}.</span>
        )}
        <span data-testid="desk-mcap-note" style={quiet}>
          {d.method ?? "NSE index membership"}.{" "}
          {d.indices.length > 0 && `Lists: ${d.indices.map((ix) => (ix.available && ix.date ? `${ix.name} (${ix.members != null ? `${fmtNum(ix.members)} members, ` : ""}${fmtDay(ix.date)})` : `${ix.name} (not on record)`)).join(" · ")}. `}
          Weights are shares of your direct stocks’ value{d.totalValueRs != null ? ` (${fmtINR(d.totalValueRs, { compact: true })})` : ""}.
          {d.fundsValueRs != null && d.fundsValueRs > 0 ? ` Funds and other holdings (${fmtINR(d.fundsValueRs, { compact: true })}) are not split.` : " Funds are not split."}
        </span>
      </div>
    );
  }
  return <Sub title="By market cap" note="Direct stocks · NSE index membership" testId="desk-portfolio-mcap">{body}</Sub>;
}

const CAP_BUCKET_INDEX: Record<CapBucket, number> = { large: 0, mid: 1, small: 2, micro: 3, unclassified: 4 };

// ── positions ────────────────────────────────────────────────────────────

const SHOWN = 8;

function Positions({ view }: { view: PortfolioView }) {
  const { mobile } = useCopilotShell();
  const [all, setAll] = useState(false);
  const stocks = view.stocks;
  if (!stocks.length) {
    return (
      <Sub title="Positions · direct stocks">
        <span data-testid="desk-portfolio-no-stocks" style={quiet}>
          No direct stocks on record. Your {plural(view.holdingsCount, "holding")} are funds or other assets; their sector exposure is in the ring above.
        </span>
      </Sub>
    );
  }
  const columns: Column<StockPosition>[] = [
    { key: "name", header: "Stock", width: "minmax(0,1.8fr)", render: (s) => <StockName symbol={s.symbol ?? s.name} name={s.name} size={22} /> },
    { key: "value", header: "Value", align: "right", num: true, render: (s) => fmtINR(s.valueRs, { compact: true }) },
    { key: "pnl", header: "P&L", align: "right", num: true, render: (s) => <span style={{ color: TONE_COLOR[signTone(s.pnlPct)] }}>{fmtPct(s.pnlPct, { signed: true })}</span> },
    {
      key: "weight",
      header: "Weight",
      align: "right",
      num: true,
      render: (s) => {
        const over = s.weightPct != null && s.weightPct > SINGLE_STOCK_LIMIT_PCT;
        return (
          <span data-testid="desk-portfolio-weight" data-over={over ? "true" : "false"} title={over ? `Above the ${SINGLE_STOCK_LIMIT_PCT}% single-stock limit` : undefined} style={{ color: over ? "var(--amber)" : "var(--cp-ink-2)", fontWeight: over ? 600 : undefined }}>
            {fmtPct(s.weightPct)}
          </span>
        );
      },
    },
  ];
  const rows = all ? stocks : stocks.slice(0, SHOWN);
  return (
    <Sub title={<>Positions · <span data-testid="desk-portfolio-stock-count">{fmtNum(stocks.length)}</span> direct {stocks.length === 1 ? "stock" : "stocks"}</>} note="Weight = share of the whole portfolio" testId="desk-portfolio-positions">
      <div style={{ margin: "0 -16px" }}>
        <DataTable columns={columns} rows={rows} rowKey={(s) => s.id} minWidth={mobile ? 330 : 430} />
      </div>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
        <span style={quiet}>
          A weight above {SINGLE_STOCK_LIMIT_PCT}% of the portfolio is marked in amber: a single-stock limit, so that one company cannot dominate the portfolio.
        </span>
        {stocks.length > SHOWN && (
          <Btn variant="ghost" data-testid="desk-portfolio-show-all" aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? "Show fewer" : `Show all ${fmtNum(stocks.length)}`}
          </Btn>
        )}
      </div>
    </Sub>
  );
}

// ── risk checks ──────────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  detail: ReactNode;
  level: string;
  tone: Tone;
}

const RATING: Record<string, { label: string; tone: Tone }> = {
  LOW: { label: "Low", tone: "mint" },
  MEDIUM: { label: "Medium", tone: "ink" },
  HIGH: { label: "High", tone: "amber" },
  VERY_HIGH: { label: "Very high", tone: "danger" },
};

const IMPACT: Record<string, { label: string; tone: Tone }> = {
  LOW: { label: "Low", tone: "mint" },
  MEDIUM: { label: "Medium", tone: "amber" },
  HIGH: { label: "High", tone: "danger" },
};

function riskFigureChecks(r: RiskAnalytics): { first: Check[]; rest: Check[]; missing: string[] } {
  const first: Check[] = [];
  const rest: Check[] = [];
  const missing: string[] = [];
  if (r.beta != null) {
    const level = r.beta > BETA_HIGH ? { label: "High", tone: "amber" as Tone } : r.beta < BETA_LOW ? { label: "Low", tone: "ink" as Tone } : { label: "Near the market", tone: "ink" as Tone };
    first.push({
      id: "beta",
      label: "Portfolio beta vs Nifty 50",
      detail: <><span data-testid="desk-risk-beta-value" className="cp-num">{fmtNum(r.beta, 2)}</span> · 1-year beta weighted by value; 1.00 moves in step with the Nifty 50</>,
      level: level.label,
      tone: level.tone,
    });
  } else missing.push("beta");
  if (r.volatilityPct != null) {
    const rating = r.rating ? RATING[r.rating] : undefined;
    rest.push({
      id: "volatility",
      label: "Volatility",
      detail: <><span data-testid="desk-risk-volatility-value" className="cp-num">{fmtPct(r.volatilityPct)}</span> a year · 1-year volatility weighted by value</>,
      level: rating?.label ?? "—",
      tone: rating?.tone ?? "ink",
    });
  } else missing.push("volatility");
  if (r.var1dRs != null || r.var1dPct != null) {
    const conf = r.varConfidencePct ?? 95;
    rest.push({
      id: "var",
      label: "1-day value at risk",
      detail: (
        <>
          <span data-testid="desk-risk-var-value" className="cp-num">{fmtINR(r.var1dRs)}{r.var1dPct != null ? ` (${fmtPct(r.var1dPct, { digits: 2 })})` : ""}</span>
          {` · a one-day loss exceeded on about ${fmtNum(100 - conf)} days in 100, at ${fmtNum(conf)}% confidence; a normal-distribution estimate from the volatility above`}
        </>
      ),
      level: "Estimate",
      tone: "ink",
    });
  } else missing.push("value at risk");
  for (const d of r.drivers) {
    const impact = d.impact ? IMPACT[d.impact] : undefined;
    rest.push({
      id: `driver-${d.type.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      label: d.label,
      detail: d.pct != null ? `${fmtPct(d.pct)} of the portfolio’s value` : "No share sent",
      level: impact?.label ?? "—",
      tone: impact?.tone ?? "ink",
    });
  }
  return { first, rest, missing };
}

function CheckRow({ c }: { c: Check }) {
  return (
    <li data-testid={`desk-risk-${c.id}`} data-level={c.level} className="grid items-start" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "2px 12px", padding: "9px 0", borderTop: "1px solid var(--cp-line)" }}>
      <span className="flex flex-col min-w-0" style={{ gap: 2 }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--cp-ink)" }}>{c.label}</span>
        <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{c.detail}</span>
      </span>
      <span data-testid="desk-risk-level" className="cp-mono-note" style={{ paddingTop: 2, textAlign: "right", color: TONE_COLOR[c.tone] }}>{c.level}</span>
    </li>
  );
}

function RiskChecks({ view }: { view: PortfolioView }) {
  const risk = useRiskAnalytics();
  const conc = usePortfolioConcentration();
  const figures = risk.data && !risk.data.empty ? riskFigureChecks(risk.data) : null;
  const checks: Check[] = [...(figures?.first ?? [])];

  const top = largestStock(view.stocks);
  if (top) {
    const over = top.weightPct > SINGLE_STOCK_LIMIT_PCT;
    checks.push({
      id: "single-stock",
      label: "Largest single-stock weight",
      detail: <><span className="inline-flex items-center" style={{ gap: 5, verticalAlign: "middle" }}><StockIcon symbol={top.symbol ?? top.name} name={top.name} size={16} />{top.symbol ?? top.name}</span> is <span data-testid="desk-risk-single-stock-value" className="cp-num">{fmtPct(top.weightPct)}</span> of the portfolio · limit {SINGLE_STOCK_LIMIT_PCT}%</>,
      level: over ? "Above limit" : "Within limit",
      tone: over ? "amber" : "mint",
    });
  }

  const lens = conc.data && !conc.data.empty ? lensOf(readConcentration(conc.data), "sector") : null;
  if (lens && lens.items.length) {
    const largest = lens.items.find((i) => !i.isResidual && i.pct != null);
    const warned = typeof conc.data?.sector?.warning === "string" && conc.data.sector.warning.trim() !== "";
    const verdict = lens.verdict ? VERDICT_META[lens.verdict] : warned ? { label: "Warning", tone: "amber" as Tone } : null;
    const parts: string[] = [];
    if (largest?.pct != null) {
      const cap = lens.capPct;
      parts.push(`${largest.name} is ${fmtPct(largest.pct)} of sector exposure${cap != null ? `, ${largest.pct > cap ? "above" : "under"} the ${fmtNum(cap)}% cap` : ""}`);
    }
    if (lens.hhi != null) parts.push(`HHI ${fmtNum(lens.hhi)}`);
    if (lens.effectiveN != null) parts.push(`${fmtNum(lens.effectiveN, 1)} effective sectors`);
    checks.push({
      id: "sector",
      label: "Sector concentration",
      detail: parts.join(" · ") || "No classified sector on record",
      level: verdict?.label ?? "—",
      tone: verdict?.tone ?? "ink",
    });
  }
  checks.push(...(figures?.rest ?? []));

  return (
    <Sub title="Risk checks" note="Whole portfolio" testId="desk-portfolio-risk">
      {checks.length > 0 && <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>{checks.map((c) => <CheckRow key={c.id} c={c} />)}</ul>}
      {risk.isPending && <LoadingBlock label="Loading beta, volatility and value at risk" rows={2} />}
      {risk.isError && <QueryProblem what="Beta, volatility and value at risk" error={risk.error} onRetry={() => risk.refetch()} />}
      {risk.data && (
        <span data-testid="desk-portfolio-risk-note" style={quiet}>
          {risk.data.coveragePct != null && `Beta, volatility and value at risk cover ${fmtPct(risk.data.coveragePct)} of the portfolio’s value: the holdings with a figure on record. `}
          {figures && figures.missing.length > 0 && `No figure on record for: ${figures.missing.join(", ")}. `}
          {`Beta above ${fmtNum(BETA_HIGH, 1)} is marked high and below ${fmtNum(BETA_LOW, 1)} low. Volatility bands and risk-driver levels are the route’s own.`}
        </span>
      )}
      <CorrelationBlock />
    </Sub>
  );
}

// ── correlated positions ─────────────────────────────────────────────────

function PairRow({ p, high }: { p: CorrPair; high: number }) {
  const flagged = p.corr >= high;
  const weights = [
    p.weightA != null && p.weightB != null ? `${fmtPct(p.weightA)} and ${fmtPct(p.weightB)} of the portfolio` : "",
    p.commonSessions != null ? `${fmtNum(p.commonSessions)} common sessions` : "",
  ].filter(Boolean).join(" · ") || null;
  return (
    <li
      data-testid="desk-corr-pair"
      data-pair={`${p.a}-${p.b}`}
      data-high={flagged ? "true" : "false"}
      className="grid items-center"
      style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "2px 12px", padding: "8px 0", borderTop: "1px solid var(--cp-line)" }}
    >
      <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px", fontSize: 13 }}>
        <span className="inline-flex items-center" style={{ gap: 5 }}><StockIcon symbol={p.a} size={18} /><span data-testid="desk-corr-a" className="cp-num" style={{ color: "var(--cp-ink)" }}>{p.a}</span></span>
        <span aria-hidden="true" style={{ color: "var(--cp-ink-4)" }}>↔</span>
        <span className="inline-flex items-center" style={{ gap: 5 }}><StockIcon symbol={p.b} size={18} /><span data-testid="desk-corr-b" className="cp-num" style={{ color: "var(--cp-ink)" }}>{p.b}</span></span>
      </span>
      <span className="flex items-center justify-end" style={{ gap: 8 }}>
        {flagged && <span data-testid="desk-corr-flag"><Pill tone="amber">High</Pill></span>}
        <span data-testid="desk-corr-value" className="cp-num" style={{ fontSize: 14, color: flagged ? "var(--amber)" : "var(--cp-ink)" }}>{fmtNum(p.corr, 2)}</span>
      </span>
      {weights && <span style={{ gridColumn: "1 / -1", fontSize: 11.5, color: "var(--cp-ink-3)" }}>{weights}</span>}
    </li>
  );
}

function CorrelationBlock() {
  const q = useCorrelation();
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Working out which holdings move together" rows={2} />;
  else if (q.isError) body = <div data-testid="desk-corr-error"><QueryProblem what="Correlated positions" error={q.error} onRetry={() => q.refetch()} /></div>;
  else {
    const d = q.data;
    const high = d.highThreshold ?? CORR_HIGH_DEFAULT;
    // The route counts flagged pairs over every pair, not only the ones it lists.
    const flagged = d.highPairs ?? d.pairs.filter((p) => p.corr >= high).length;
    const skipped = d.skipped.length > 0 && (
      <span data-testid="desk-corr-skipped" style={quiet}>
        Not compared: {d.skipped.map((s) => `${s.symbol}${s.reason ? ` (${s.reason})` : ""}`).join("; ")}.
      </span>
    );
    body = d.pairs.length === 0 ? (
      <div data-testid="desk-corr-none" className="flex flex-col" style={{ gap: 6 }}>
        <span style={quiet}>Fewer than two of your stocks have enough daily prices to compare{d.sessions ? ` over ${fmtNum(d.sessions)} sessions` : ""}.</span>
        {skipped}
      </div>
    ) : (
      <div className="flex flex-col" style={{ gap: 8 }}>
        <span data-testid="desk-corr-summary" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {flagged > 0 ? `${plural(flagged, "pair")} at ${fmtNum(high, 2)} or above` : `No pair at ${fmtNum(high, 2)} or above`}
          {d.pairsTotal != null ? ` of ${plural(d.pairsTotal, "pair")}` : ""}
          {d.avgCorr != null ? ` · average ${fmtNum(d.avgCorr, 2)}` : ""}
          {d.holdingsUsed != null ? ` · ${plural(d.holdingsUsed, "stock")} compared` : ""}
          {d.pairsTotal != null && d.pairsTotal > d.pairs.length ? ` · top ${fmtNum(d.pairs.length)} listed` : ""}
        </span>
        <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
          {d.pairs.map((p) => <PairRow key={`${p.a}-${p.b}`} p={p} high={high} />)}
        </ul>
        {skipped}
      </div>
    );
    body = (
      <>
        {body}
        <span data-testid="desk-corr-method" style={quiet}>
          {d.method ?? "Correlation of daily returns"} over {fmtNum(d.sessions ?? CORR_SESSIONS)} sessions{d.minSessions != null ? ` (a stock needs at least ${fmtNum(d.minSessions)})` : ""}{d.source ? ` · ${d.source}` : ""}{d.asOf ? ` · end of day ${fmtDay(d.asOf)}` : ""}. 1.00 = always move together; a pair at {fmtNum(high, 2)} or above is flagged. Most correlated first.
        </span>
      </>
    );
  }
  return (
    <div data-testid="desk-portfolio-correlation" className="flex min-w-0 flex-col" style={{ gap: 8, paddingTop: 6 }}>
      <span style={{ fontSize: 13, fontWeight: 500, color: "var(--cp-ink)" }}>Correlated positions</span>
      {body}
    </div>
  );
}

// ── left card ────────────────────────────────────────────────────────────

function HubCard() {
  const { go } = useCopilotShell();
  const q = useHoldingsEnriched();
  const props = { title: "Portfolio · broker hub", pill: <Pill tone="indigo">Read-only</Pill>, aside: <SourcesLine />, testId: "desk-portfolio-hub" };

  if (q.isPending) return <Card {...props}><LoadingBlock label="Loading your holdings" rows={4} /></Card>;
  if (q.isError) return <Card {...props}><ErrorBlock title="Your holdings didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} /></Card>;

  const view = readPortfolio(q.data);
  if (view.holdingsCount === 0) {
    return (
      <Card {...props}>
        <div data-testid="desk-portfolio-empty">
          <EmptyBlock
            title="No holdings on record yet"
            body="Connect a broker account (read-only) or import a statement, and your positions, sector split and risk checks show here."
            action={<Btn variant="primary" data-testid="desk-portfolio-connect" onClick={() => go("page/brokers")}>Connect or import your portfolio</Btn>}
          />
        </div>
      </Card>
    );
  }

  const stockShare = view.stocksValueRs != null && view.totalValueRs ? (view.stocksValueRs / view.totalValueRs) * 100 : null;
  return (
    <Card {...props}>
      <div className="flex flex-col" style={{ gap: 6 }}>
        <div className="flex flex-wrap items-end" style={{ gap: "10px 28px" }}>
          <div className="flex flex-col" style={{ gap: 2 }}>
            <span className="cp-mono-note">Total value</span>
            <span data-testid="desk-portfolio-value" className="cp-metric">{fmtINR(view.totalValueRs, { compact: true })}</span>
          </div>
          <div className="flex flex-col" style={{ gap: 2, paddingBottom: 4 }}>
            <span className="cp-mono-note">Total P&amp;L</span>
            <span data-testid="desk-portfolio-pnl" className="cp-num" style={{ fontSize: 17, color: TONE_COLOR[signTone(view.totalPnlRs)] }}>
              {fmtINR(view.totalPnlRs, { compact: true, signed: true })} · {fmtPct(view.totalPnlPct, { signed: true })}
            </span>
          </div>
        </div>
        <span style={quiet}>
          {plural(view.holdingsCount, "holding")} on record
          {view.stocksValueRs != null && ` · direct stocks ${fmtINR(view.stocksValueRs, { compact: true })}${stockShare != null ? ` (${fmtPct(stockShare)} of the value)` : ""}`}
        </span>
      </div>
      <SectorRing />
      <CapSplitBlock />
      <Positions view={view} />
      <RiskChecks view={view} />
    </Card>
  );
}

// ── right card ───────────────────────────────────────────────────────────

function JournalBlock() {
  const { go } = useCopilotShell();
  const q = useJournalSummary();
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading your trade journal" rows={2} />;
  else if (q.isError) body = <QueryProblem what="Your trade journal" error={q.error} onRetry={() => q.refetch()} />;
  else if (q.data.openCount + q.data.closedCount === 0) {
    body = (
      <div data-testid="desk-journal-empty" className="flex flex-col items-start" style={{ gap: 8 }}>
        <span style={quiet}>No trades are logged in your journal yet. Trades you log on the Trader desk are counted here.</span>
        <Btn onClick={() => go("trader")}>Open the Trader desk</Btn>
      </div>
    );
  } else {
    const j = q.data;
    const tiles: Array<{ k: string; v: ReactNode; s: string; testId: string; tone?: Tone }> = [
      { k: "Open", v: fmtNum(j.openCount), s: "Trades still open", testId: "desk-journal-open" },
      { k: "Closed", v: fmtNum(j.closedCount), s: "Closed or stopped", testId: "desk-journal-closed" },
      { k: "Win rate", v: fmtPct(j.winRatePct), s: `${fmtNum(j.winCount)} won · ${fmtNum(j.lossCount)} lost`, testId: "desk-journal-win-rate" },
      { k: "Realised P&L", v: fmtINR(j.realizedRs, { signed: true }), s: "On closed trades", testId: "desk-journal-realised", tone: signTone(j.realizedRs) },
    ];
    body = (
      <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
        {tiles.map((t) => (
          <div key={t.k} className="flex flex-col min-w-0" style={{ gap: 3, padding: "10px 12px", borderRadius: 10, background: "var(--bg-2)" }}>
            <span className="cp-eyebrow">{t.k}</span>
            <span data-testid={t.testId} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 21, color: TONE_COLOR[t.tone ?? "ink"] }}>{t.v}</span>
            <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{t.s}</span>
          </div>
        ))}
      </div>
    );
  }
  return <Sub title="Your trade journal" note="Trades you logged" testId="desk-journal">{body}</Sub>;
}

type BucketSet = "universe" | "selected";

const SAMPLE_NOTE: Record<PaperSample, string> = {
  forward: "Forward sample: sessions recorded as they happened, after the model was frozen.",
  replay: "Replay sample: the frozen model run over 2025 sessions after the fact; not live.",
};

function CalibrationBars({ rows }: { rows: CalibrationRow[] }) {
  const top = Math.max(10, ...rows.flatMap((r) => [r.predictedPct, r.realisedPct]));
  const scale = Math.ceil(top / 10) * 10;
  const at = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;
  const band = (r: CalibrationRow) => `${fmtNum(r.loPct)}–${fmtNum(r.hiPct)}%`;
  return (
    <div data-testid="desk-calibration" className="flex flex-col" style={{ gap: 12 }}>
      <div className="flex flex-wrap" style={{ gap: "4px 16px", fontSize: 11, color: "var(--cp-ink-3)" }}>
        <span className="flex items-center" style={{ gap: 6 }}><span aria-hidden="true" style={{ width: 14, height: 8, borderRadius: 2, background: "var(--cp-indigo)" }} />Realised · how often the move happened</span>
        <span className="flex items-center" style={{ gap: 6 }}><span aria-hidden="true" style={{ width: 2, height: 12, background: "var(--cp-ink)" }} />Predicted · the model’s average</span>
      </div>
      {rows.map((r) => (
        <div key={r.loPct} data-testid="desk-calibration-row" data-lo={Math.round(r.loPct)} className="grid items-center" style={{ gridTemplateColumns: "64px minmax(0,1fr)", gap: "4px 10px" }}>
          <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-2)" }}>{band(r)}</span>
          <span
            role="img"
            aria-label={`Predicted ${band(r)}: realised ${fmtPct(r.realisedPct)}, predicted ${fmtPct(r.predictedPct)}`}
            style={{ position: "relative", display: "block", height: 10, borderRadius: 3, background: "var(--bg-2)" }}
          >
            <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: at(r.realisedPct), borderRadius: 3, background: "var(--cp-indigo)" }} />
            <span style={{ position: "absolute", top: -3, bottom: -3, left: at(r.predictedPct), width: 2, marginLeft: -1, borderRadius: 1, background: "var(--cp-ink)" }} />
          </span>
          <span />
          <span style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>
            Realised <span data-testid="desk-calibration-realised" className="cp-num" style={{ color: "var(--cp-ink)" }}>{fmtPct(r.realisedPct)}</span>
            {" · predicted "}<span data-testid="desk-calibration-predicted" className="cp-num" style={{ color: "var(--cp-ink)" }}>{fmtPct(r.predictedPct)}</span>
            {` · ${fmtSigned(r.errorPts, 1)} pt · ${plural(r.n, "prediction")}`}
          </span>
        </div>
      ))}
      <span className="cp-mono-note">Scale 0–{fmtNum(scale)}%</span>
    </div>
  );
}

function CalibrationBlock() {
  const [sample, setSample] = useState<PaperSample>("forward");
  const [set, setSet] = useState<BucketSet>("universe");
  const q = usePaperEvaluation(sample, "P5-NEXT");

  if (q.data?.kind === "no_access") {
    return (
      <Sub title="The model’s record · paper trades" testId="desk-paper">
        <div data-testid="desk-paper-no-access">
          <EmptyBlock
            title="The paper-trade record is not enabled for this account"
            body="This research record is limited to invited accounts. An admin can turn on the move-odds research feature for you."
          />
        </div>
      </Sub>
    );
  }

  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading the model’s evaluation" rows={3} />;
  else if (q.isError) body = <ErrorBlock title="The model’s evaluation didn’t load" error={q.error} onRetry={() => q.refetch()} />;
  else if (q.data.kind === "error") body = <ErrorBlock title="The model’s evaluation didn’t load" error={q.data.message} onRetry={() => q.refetch()} />;
  else if (q.data.kind !== "ok") {
    body = <span data-testid="desk-paper-empty" style={quiet}>No evaluation of the {sample} sample is stored yet. The engine stores one after each run.</span>;
  } else {
    const ev = q.data.data;
    const rows = calibrationRows(ev.buckets[set]);
    body = (
      <div className="flex flex-col" style={{ gap: 12 }}>
        <span data-testid="desk-paper-statement" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          {ev.statement.text} {plural(ev.sessions.counted, "counted session")}; the pre-registered minimum is {fmtNum(ev.statement.min_sessions)}.
        </span>
        {rows.length ? (
          <CalibrationBars rows={rows} />
        ) : (
          <span data-testid="desk-calibration-none" style={quiet}>
            No probability bucket has predictions with an outcome yet in the {sample} sample{sample === "forward" ? "; the replay sample has the longer record" : ""}.
          </span>
        )}
        <span style={quiet}>
          P5-NEXT: the model’s probability that a stock’s high reaches +5% in the next session. Predicted is its average probability for the stocks in a bucket; realised is how often that happened.
          {q.data.asOf ? ` Latest evaluation stored for the session of ${fmtDay(q.data.asOf)}.` : ""}
        </span>
      </div>
    );
  }

  return (
    <Sub title="The model’s record · predicted vs realised" note="Paper trades · no orders" testId="desk-paper">
      <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
        <Choices<PaperSample>
          label="Sample"
          testId="desk-paper-sample"
          value={sample}
          onChange={setSample}
          options={[{ value: "forward", label: "Forward" }, { value: "replay", label: "Replay · 2025" }]}
        />
        <Choices<BucketSet>
          label="Bucket set"
          testId="desk-paper-set"
          value={set}
          onChange={setSet}
          options={[{ value: "universe", label: "Every eligible stock" }, { value: "selected", label: "Selected five" }]}
        />
      </div>
      <span data-testid="desk-paper-sample-note" style={quiet}>{SAMPLE_NOTE[sample]}</span>
      {body}
    </Sub>
  );
}

function RecordCard() {
  return (
    <Card title="Your trades and the model’s record" testId="desk-portfolio-record">
      <JournalBlock />
      <CalibrationBlock />
    </Card>
  );
}

// ── tab ──────────────────────────────────────────────────────────────────

export default function PortfolioTab() {
  return (
    <div data-testid="desk-portfolio" className="flex flex-col min-w-0" style={{ gap: 16 }}>
      <div className="grid items-start" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,380px),1fr))", gap: 16 }}>
        <HubCard />
        <RecordCard />
      </div>
      <Card title="Your paper trades and price alerts" pill={<Pill tone="amber">Simulated · no orders</Pill>} testId="desk-portfolio-paper">
        <PaperTradesBlock />
        <AlertsBlock />
      </Card>
      <BrokerPositions />
      <Footnote>Holdings and risk figures are as Nivesh last valued them; broker connections are read-only and nothing here places an order.</Footnote>
    </div>
  );
}
