/**
 * Portfolio ledger — health, totals, the split by type, every holding with the
 * ones that need a look first, and what is on record behind them: realised
 * gains, month-end value, statements, transactions and SIPs.
 * Design: NVPages.dc.html, page === "ledger".
 *
 * It carries what the original Portfolio page shows from the same endpoints
 * (src/pages/Portfolio): the four headline figures, the allocation-by-type
 * bar, top gainers and losers, the holdings table's columns and filters, and
 * the SIP list.
 *
 * Data:
 *   health, totals, holdings   GET /api/portfolio/holdings-enriched         (useHoldingsEnriched)
 *   source of each holding     GET /api/portfolio/holdings                  (portfolio/LedgerHoldings)
 *   correct a holding          PUT /api/portfolio/holdings/{id}             (portfolio/LedgerHoldings)
 *   realised gains             GET /api/portfolio/capital-gains-statement   (useRealisedGains)
 *   month-end value            GET /api/portfolio/trend + /api/onboarding/state (usePortfolioNavHistory)
 *   change since last month    GET /api/portfolio/compare?from=             (usePortfolioCompare)
 *   statements, transactions, SIPs
 *                              GET /api/portfolio/cas-snapshots, /transactions, /sips (portfolio/LedgerSections)
 *
 * Not connected: a log of corrections, matching a holding to another name or
 * merging two, and a time-weighted return.
 */
import { useMemo } from "react";
import { useHoldingsEnriched, usePortfolioNavHistory } from "@/hooks/use-portfolio";
import type { EnrichedHoldingsRes } from "@/services/contracts/portfolio.contract";
import {
  EmptyBlock, ErrorBlock, Footnote, LoadingBlock, NotConnected, Screen, ScreenHeader, Section, Tiles,
  TONE_COLOR, fmtDate, fmtINR, fmtPct, signTone, type TileItem, type Tone,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { usePortfolioContext } from "../lib/use-portfolio-context";
import { Holdings } from "./portfolio/LedgerHoldings";
import { Movers, Sips, Statements, Transactions, TypeSplit } from "./portfolio/LedgerSections";
import {
  isoDay, loadError, num, readHealth, readNavPoints, usePortfolioCompare, useRealisedGains,
  type HealthView, type ValuePoint,
} from "./portfolio/data";
import { HeaderRow, NoPortfolio } from "./portfolio/parts";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const RING = 2 * Math.PI * 40;

const clampPct = (n: number): number => Math.min(100, Math.max(0, n));

// ── health ───────────────────────────────────────────────────────────────

/** Presentation only: strong scores in mint, weak ones in amber. */
function scoreColor(score: number): string {
  return score >= 75 ? "var(--mint)" : score < 60 ? "var(--amber)" : "var(--cp-ink)";
}

function HealthCard({ health }: { health: HealthView | null }) {
  const { mobile } = useCopilotShell();
  if (!health) {
    return <EmptyBlock title="No health score yet" body="The health score is worked out once your holdings are priced and scored. It has not been computed for this portfolio yet." />;
  }
  const score = Math.round(health.score);
  return (
    <div data-testid="ledger-health" className="cp-card-raised flex flex-wrap items-center" style={{ gap: 20, padding: 18 }}>
      <div role="img" aria-label={`Portfolio health ${score} out of 100`} style={{ position: "relative", width: 96, height: 96, flex: "none" }}>
        <svg viewBox="0 0 96 96" width={96} height={96} aria-hidden="true" style={{ transform: "rotate(-90deg)" }}>
          <circle cx="48" cy="48" r="40" fill="none" stroke="var(--bg-3)" strokeWidth="7" />
          <circle cx="48" cy="48" r="40" fill="none" stroke="var(--mint)" strokeWidth="7" strokeLinecap="round" strokeDasharray={`${(clampPct(health.score) / 100) * RING} ${RING}`} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
          <span data-testid="ledger-health-score" style={{ fontFamily: "var(--display)", fontSize: 32, lineHeight: 1 }}>{score}</span>
        </div>
      </div>
      <div className="flex min-w-0 flex-col" style={{ flex: "1 1 220px", gap: 6 }}>
        <span className="cp-eyebrow">Portfolio health{health.grade ? <> · grade <span data-testid="ledger-health-grade">{health.grade}</span></> : null}</span>
        {health.summary && <span className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: mobile ? 18 : 20, lineHeight: 1.3 }}>{health.summary}</span>}
        {health.lowConfidence && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Low confidence: some inputs behind this score are estimated.</span>}
      </div>
      {health.components.length > 0 && (
        <div className="grid" style={{ flex: "1 1 280px", gridTemplateColumns: "repeat(auto-fit,minmax(84px,1fr))", gap: 10 }}>
          {health.components.map((c) => (
            <div key={c.key} data-testid={`ledger-health-${c.key}`} className="flex flex-col" style={{ gap: 4 }} title={c.note || undefined}>
              <span className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 20, color: scoreColor(c.score) }}>{Math.round(c.score)}</span>
              <span aria-hidden="true" style={{ display: "block", height: 3, borderRadius: 2, background: scoreColor(c.score), width: `${clampPct(c.score)}%` }} />
              <span style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>
                {c.name}{c.lowConfidence ? " · est." : ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── realised gains ───────────────────────────────────────────────────────

function Metric({ k, value, tone, testId }: { k: string; value: string; tone?: Tone; testId?: string }) {
  return (
    <div className="flex flex-col" style={{ gap: 4 }}>
      <span className="cp-eyebrow">{k}</span>
      <span data-testid={testId} className="cp-num" style={{ fontSize: 18, color: TONE_COLOR[tone ?? "ink"] }}>{value}</span>
    </div>
  );
}

function RealisedGains() {
  const q = useRealisedGains();
  if (q.isPending) return <LoadingBlock label="Loading realised gains" rows={2} />;
  if (q.isError) return <ErrorBlock title="Realised gains didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  const g = q.data;
  if (g.lots === 0) {
    return (
      <EmptyBlock
        title={`No realised gains${g.fy ? ` in ${g.fy}` : ""}`}
        body="Nivesh found no sales in your transactions for this financial year. Gains and losses appear here once a sale is on record."
      />
    );
  }
  const total = g.stcgRs + g.ltcgRs;
  return (
    <Section title={`Realised gains${g.fy ? ` · ${g.fy}` : ""}`} note={`${g.lots} sold ${g.lots === 1 ? "lot" : "lots"} · FIFO`}>
      <div className="flex flex-col" style={{ gap: 12 }}>
        <div data-testid="ledger-realised" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 14 }}>
          <Metric k="Total realised" value={fmtINR(total, { signed: true })} tone={signTone(total)} testId="ledger-realised-total" />
          <Metric k="Short term" value={fmtINR(g.stcgRs, { signed: true })} tone={signTone(g.stcgRs)} testId="ledger-realised-stcg" />
          <Metric k="Long term" value={fmtINR(g.ltcgRs, { signed: true })} tone={signTone(g.ltcgRs)} testId="ledger-realised-ltcg" />
          <Metric k="Estimated tax" value={fmtINR(g.estimatedTaxRs)} testId="ledger-realised-tax" />
        </div>
        <Footnote>Equity only · indicative, not a tax-filing figure</Footnote>
      </div>
    </Section>
  );
}

// ── month-end value ──────────────────────────────────────────────────────

interface MonthPoint {
  /** "2026-10". */
  key: string;
  /** "Oct". */
  month: string;
  /** "Oct 2026". */
  label: string;
  valueRs: number;
}

/** Last recorded value in each calendar month, most recent twelve. */
function monthEnds(points: ValuePoint[]): MonthPoint[] {
  const last = new Map<string, ValuePoint>();
  for (const p of points) {
    const key = p.date.slice(0, 7);
    const prev = last.get(key);
    if (!prev || p.date >= prev.date) last.set(key, p);
  }
  return [...last.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-12)
    .map(([key, v]) => {
      const month = MONTHS[Number(key.slice(5, 7)) - 1] ?? key.slice(5, 7);
      return { key, month, label: `${month} ${key.slice(0, 4)}`, valueRs: v.valueRs };
    });
}

function SinceLastMonth() {
  const from = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return isoDay(d);
  }, []);
  const q = usePortfolioCompare(from);
  if (q.isPending) return <LoadingBlock label="Comparing with last month" rows={1} />;
  if (q.isError) return <ErrorBlock title="The comparison with last month didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  const c = q.data;
  if (!c) return null;
  if (!c.fromDate) {
    return <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>No snapshot from a month ago to compare with yet.</span>;
  }
  const facts: Array<{ k: string; v: string; tone: Tone }> = [];
  if (c.valueDeltaRs != null) {
    facts.push({ k: "Value", v: `${fmtINR(c.valueDeltaRs, { compact: true, signed: true })}${c.valuePctChange != null ? ` (${fmtPct(c.valuePctChange, { signed: true })})` : ""}`, tone: signTone(c.valueDeltaRs) });
  }
  if (c.healthDelta != null) {
    facts.push({ k: "Health", v: `${c.healthDelta > 0 ? "+" : c.healthDelta < 0 ? "−" : ""}${Math.abs(c.healthDelta).toFixed(1)} pts`, tone: signTone(c.healthDelta) });
  }
  if (c.added.length + c.removed.length > 0) {
    facts.push({ k: "Top holdings", v: `+${c.added.length} in · −${c.removed.length} out`, tone: "ink" });
  }
  return (
    <div data-testid="ledger-compare" className="flex flex-wrap items-baseline" style={{ gap: "6px 18px", fontSize: 12, color: "var(--cp-ink-3)" }}>
      <span>Since {fmtDate(c.fromDate)}</span>
      {facts.map((f) => (
        <span key={f.k}>{f.k} <span className="cp-num" style={{ color: f.tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[f.tone] }}>{f.v}</span></span>
      ))}
      {facts.length === 0 && <span>No change recorded.</span>}
    </div>
  );
}

function Snapshots() {
  const q = usePortfolioNavHistory("1y");
  if (q.isPending) return <LoadingBlock label="Loading snapshots" rows={3} />;
  if (q.isError) return <ErrorBlock title="Snapshots didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  const months = monthEnds(readNavPoints(q.data));
  if (!months.length) {
    return <EmptyBlock title="No snapshots yet" body="Nivesh records your portfolio value as statements are imported and at the end of each day. The month-by-month view fills in from the first one." />;
  }
  const max = Math.max(...months.map((m) => m.valueRs));
  const latest = months[months.length - 1];
  return (
    <Section title="Month-end value" note={<>Latest · {latest.label} · <span data-testid="ledger-snapshot-latest">{fmtINR(latest.valueRs, { compact: true })}</span></>}>
      <div className="flex flex-col" style={{ gap: 12 }}>
        <div aria-hidden="true" data-testid="ledger-snapshots" className="flex items-stretch" style={{ gap: 8, height: 96 }}>
          {months.map((m) => (
            <div key={m.key} className="flex min-w-0 flex-col" style={{ flex: 1, gap: 4 }} title={`${m.label}: ${fmtINR(m.valueRs, { compact: true })}`}>
              <div className="flex items-end" style={{ flex: 1 }}>
                <span style={{ display: "block", width: "100%", height: `${Math.max(2, (m.valueRs / max) * 100)}%`, background: "var(--cp-indigo-soft)", borderTop: "2px solid var(--cp-indigo)", borderRadius: "2px 2px 0 0" }} />
              </div>
              <span style={{ fontFamily: "var(--mono)", fontSize: 9, textAlign: "center", whiteSpace: "nowrap", overflow: "hidden", color: "var(--cp-ink-3)" }}>{m.month.toUpperCase()}</span>
            </div>
          ))}
        </div>
        <ul className="sr-only">
          {months.map((m) => <li key={m.key}>{m.label}: {fmtINR(m.valueRs, { compact: true })}</li>)}
        </ul>
        <SinceLastMonth />
      </div>
    </Section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

function LedgerBody({ data }: { data: EnrichedHoldingsRes }) {
  const pf = usePortfolioContext();
  const gain = num(data.totals?.pnl_rs);
  const withXirr = data.holdings.filter((h) => h.xirr_pct != null).length;
  const tiles: TileItem[] = [
    {
      k: "Market value",
      v: <span data-testid="ledger-market-value">{fmtINR(num(data.totals?.value_rs), { compact: true })}</span>,
      s: pf.statementPeriod ? <span data-testid="ledger-statement-period">Holdings from the {pf.statementPeriod} statement</span> : "At the latest prices on record",
    },
    { k: "Invested", v: <span data-testid="ledger-invested">{fmtINR(num(data.totals?.invested_rs), { compact: true })}</span>, s: "Cost basis on record" },
    {
      k: "Unrealised",
      v: <span data-testid="ledger-unrealised">{fmtINR(gain, { compact: true, signed: true })}</span>,
      s: <span data-testid="ledger-unrealised-pct">{fmtPct(num(data.totals?.pnl_pct), { signed: true })}</span>,
      tone: signTone(gain),
    },
    { k: "XIRR", v: <span data-testid="ledger-xirr">{fmtPct(num(data.totals?.xirr_pct))}</span>, s: `${withXirr} of ${data.holdings.length} holdings` },
  ];
  return (
    <>
      <HealthCard health={readHealth(data.health)} />
      <Tiles items={tiles} min={140} />
      <TypeSplit parts={pf.typeSplit} />
      <Movers holdings={data.holdings} />
      <Holdings holdings={data.holdings} />
      <NotConnected
        testId="ledger-corrections-not-connected"
        title="A log of corrections is not kept"
        body="You can correct a holding’s buy price, purchase date or units from its row above. What is not there yet: a list of the corrections you made with a way to undo one, matching a holding to a different fund or stock, and merging two rows that are the same holding."
        needs={[
          "A corrections log written by PUT /api/portfolio/holdings/{id} (what changed, when, the value before) and an endpoint to list and undo entries",
          "Corrections that survive the next statement import: an import replaces every holding row, edits included",
          "An endpoint to re-point a holding at another instrument, and one to merge two holding rows",
          "A reconciliation status for each holding (statement value against the value worked out from units and price)",
        ]}
      />
      <RealisedGains />
      <Snapshots />
      <Statements />
      <Transactions />
      <Sips />
    </>
  );
}

export default function LedgerScreen() {
  const { ask } = useCopilotShell();
  const q = useHoldingsEnriched();
  const count = q.data?.holdings.length ?? 0;
  const value = num(q.data?.totals?.value_rs);
  return (
    <Screen testId="screen-page-ledger" width={960}>
      <HeaderRow askLabel="Analyse my portfolio" onAsk={() => ask("Analyse my portfolio: what stands out, and what should I look at first?")}>
        <ScreenHeader
          eyebrow="Portfolio ledger"
          title={count > 0
            ? <><span data-testid="ledger-count">{count}</span> {count === 1 ? "holding" : "holdings"}, <em data-testid="ledger-total">{fmtINR(value, { compact: true })}</em></>
            : "Your holdings"}
          sub="Every holding Nivesh has on record for you, with the ones that need a look listed first."
        />
      </HeaderRow>
      {q.isPending ? (
        <LoadingBlock label="Loading your holdings" rows={4} />
      ) : q.isError ? (
        <ErrorBlock title="Your holdings didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />
      ) : q.data.holdings.length === 0 ? (
        <NoPortfolio body="Import a statement or connect a broker and every holding will be listed here, with anything that needs a look flagged." />
      ) : (
        <LedgerBody data={q.data} />
      )}
    </Screen>
  );
}
