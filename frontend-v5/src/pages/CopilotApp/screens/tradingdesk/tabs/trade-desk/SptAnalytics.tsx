/**
 * Trade Desk › Paper Trading › Analytics (?tab=trade&view=paper&sub=analytics) — Scanner-to-Paper Trading (owner, 5 Nov 2026;
 * PRD §13, §19.7; docs/scanner_paper_trading/DESIGN.md). Test cases SPT-UI-P-13 … P-15 in test_reports/spt_ui_paper_TESTCASES.md.
 *
 *   1. Scanner outcomes — GET /api/v1/analytics/scanners (services/spt/outcomes/analytics.py): per scanner / category / score
 *      band, the signals and per horizon (T+1/5/10/20) the measured count, hit rate with its 95 % Wilson interval and the average
 *      return; groups under the API's minimum sample are flagged with its own note. Counts of what happened, not probabilities.
 *   2. Your paper results — GET /api/v1/paper/trades (the caller's CLOSED SPT positions), computed here ONLY from the returned
 *      trades, each formula shown (PRD §13.2–13.4). A trade without a net P&L is left out and counted as such.
 * Read-only. Nothing here reaches a broker.
 */
import { useMemo, useState, type ReactNode } from "react";
import { LoadingBlock } from "../../../../components/ui";
import { QueryProblem } from "../../../trading/parts";
import { quiet } from "./parts";
import { MONO, Pill, card, eyebrow, serifTitle, signColor } from "./pnl-ui";
import { HORIZONS, resultStats, scannerOfSignalId, useScannerAnalytics, useSptTrades, type HorizonKey, type OutcomeRow, type SptTrade } from "./spt-api";
import { Section, count, fixed, input, mono, pct, rupees, useNarrow } from "./spt-parts";

const H_LABEL: Record<HorizonKey, string> = { t1: "T+1", t5: "T+5", t10: "T+10", t20: "T+20" };
type Group = "scanner" | "category" | "band";
const GROUPS: Array<[Group, string]> = [["scanner", "By scanner"], ["category", "By category"], ["band", "By score band"]];

const signedPct = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}%`);

export default function SptAnalytics() {
  const [narrow, ref] = useNarrow(640);
  return (
    <div ref={ref} data-testid="spt-analytics" data-narrow={narrow ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 22 }}>
      <header className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span style={eyebrow}>Paper Trading · Scanner-to-paper</span>
        <h2 className="m-0" style={serifTitle}>Analytics</h2>
        <span style={quiet}>Two separate things: what the scanners' signals did in the market, and what your paper trades from them did.</span>
      </header>
      <ScannerOutcomes narrow={narrow} />
      <PaperResults narrow={narrow} />
    </div>
  );
}

// ── 1. scanner outcomes ──────────────────────────────────────────────────

function ScannerOutcomes({ narrow }: { narrow: boolean }) {
  const [kind, setKind] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [group, setGroup] = useState<Group>("scanner");
  const q = useScannerAnalytics({ from, to, kind });
  const d = q.data;
  const rows = d ? (group === "scanner" ? d.byScanner : group === "category" ? d.byCategory : d.byBand) : [];
  return (
    <section data-testid="spt-an-scanners" className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", gap: 12, padding: "16px 16px 14px" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
        <h3 className="cp-eyebrow m-0" style={{ color: "var(--cp-ink-2)" }}>Scanner signal outcomes</h3>
        <span data-testid="spt-an-not-prob" style={{ ...quiet, fontSize: 11 }}>Counts of what happened, not probabilities.</span>
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <select data-testid="spt-an-kind" aria-label="Signal kind" value={kind} onChange={(e) => setKind(e.target.value)} style={input}>
          <option value="">All signals</option><option value="list">Scanner list marks</option><option value="strong">Strong signals</option>
        </select>
        <select data-testid="spt-an-group" aria-label="Group" value={group} onChange={(e) => setGroup(e.target.value as Group)} style={input}>
          {GROUPS.map(([g, l]) => <option key={g} value={g}>{l}</option>)}
        </select>
        <label className="flex items-center" style={{ gap: 4, ...quiet }}>From <input data-testid="spt-an-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} style={input} /></label>
        <label className="flex items-center" style={{ gap: 4, ...quiet }}>To <input data-testid="spt-an-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} style={input} /></label>
        {d && <span data-testid="spt-an-range" style={{ ...quiet, fontSize: 11 }}>{d.from} to {d.to}{d.version ? ` · ${d.version}` : ""}</span>}
      </div>
      {q.isError ? <QueryProblem what="Scanner analytics" error={q.error} onRetry={() => q.refetch()} />
        : q.isPending ? <LoadingBlock label="Reading scanner outcomes" rows={3} />
        : !d ? null : (
          <>
            {d.totals && <TotalsLine t={d.totals} />}
            {rows.length === 0 ? <span data-testid="spt-an-empty" style={quiet}>No signal outcome is recorded in this range.</span>
              : narrow ? <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>{rows.map((r) => <OutcomeCard key={r.key} r={r} />)}</div>
              : <OutcomeTable rows={rows} />}
            <ul data-testid="spt-an-notes" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, ...quiet, fontSize: 11 }}>
              {d.note && <li>{d.note}</li>}
              {d.minSample != null && <li>A group with fewer than {d.minSample} measured signals is marked “small sample”: too few to draw a conclusion.</li>}
              <li>Hit rate = the share of measured signals with a positive return in the signal’s own direction; the range in brackets is its 95 % interval.</li>
            </ul>
          </>
        )}
    </section>
  );
}

function SmallTag({ on, note }: { on: boolean | null; note?: string | null }) {
  if (!on) return null;
  return <Pill tone="amber" testId="spt-an-small" title={note ?? undefined} style={{ padding: "1px 6px", fontSize: 9 }}>small sample</Pill>;
}

function HorizonCell({ r, h }: { r: OutcomeRow; h: HorizonKey }) {
  const x = r.horizons[h];
  if (!x) return <span style={{ color: "var(--cp-ink-3)" }}>—</span>;
  return (
    <span data-testid={`spt-an-${h}`} className="flex min-w-0 flex-col" style={{ gap: 2, ...mono, fontSize: 11.5 }}>
      <span>n {count(x.n)}{x.smallSample ? " ·" : ""} {x.smallSample ? <SmallTag on note={r.note} /> : null}</span>
      <span>hit {pct(x.hitRatePct)}{x.ci ? <span style={{ color: "var(--cp-ink-3)" }}> ({x.ci[0].toFixed(1)}–{x.ci[1].toFixed(1)})</span> : null}</span>
      <span style={{ color: signColor(x.avgReturnPct) }}>avg {signedPct(x.avgReturnPct)}</span>
    </span>
  );
}

function TotalsLine({ t }: { t: OutcomeRow }) {
  return (
    <div data-testid="spt-an-totals" className="flex flex-wrap items-baseline" style={{ gap: "4px 16px", fontSize: 12.5 }}>
      <span style={eyebrow}>All signals</span>
      <span style={mono}>{count(t.signals)} signals</span>
      {HORIZONS.map((h) => {
        const x = t.horizons[h];
        return x ? <span key={h} style={mono}>{H_LABEL[h]}: n {count(x.n)} · hit {pct(x.hitRatePct)} · avg {signedPct(x.avgReturnPct)}</span> : null;
      })}
      <SmallTag on={t.smallSample} note={t.note} />
    </div>
  );
}

const COLS = "minmax(0,1.4fr) minmax(0,0.6fr) repeat(4,minmax(0,1fr)) minmax(0,1fr)";

function OutcomeTable({ rows }: { rows: OutcomeRow[] }) {
  const hasPlan = rows.some((r) => r.plan);
  return (
    <div data-testid="spt-an-table" style={{ overflowX: "auto" }}>
      <div style={{ minWidth: 860 }}>
        <div className="grid" style={{ gridTemplateColumns: COLS, gap: 8, padding: "6px 0", borderBottom: "1px solid var(--cp-line)" }}>
          {["Group", "Signals", ...HORIZONS.map((h) => H_LABEL[h]), hasPlan ? "Plan outcomes (scan-plan-v3)" : "Fade"].map((h) => <span key={h} style={{ ...eyebrow, fontSize: 9.5 }}>{h}</span>)}
        </div>
        {rows.map((r) => (
          <div key={r.key} data-testid="spt-an-row" data-key={r.key} data-small={r.smallSample ? "true" : "false"} className="grid" style={{ gridTemplateColumns: COLS, gap: 8, padding: "9px 0", borderBottom: "1px solid var(--cp-line)", alignItems: "start", fontSize: 12.5 }}>
            <span className="flex min-w-0 flex-col items-start" style={{ gap: 3, overflowWrap: "anywhere" }}>{r.key}<SmallTag on={r.smallSample} note={r.note} /></span>
            <span data-testid="spt-an-signals" style={mono}>{count(r.signals)}</span>
            {HORIZONS.map((h) => <HorizonCell key={h} r={r} h={h} />)}
            <PlanCell r={r} />
          </div>
        ))}
      </div>
    </div>
  );
}

function PlanCell({ r }: { r: OutcomeRow }) {
  if (r.plan) {
    return (
      <span data-testid="spt-an-plan" className="flex flex-col" style={{ gap: 2, ...mono, fontSize: 11.5 }}>
        <span>decided {count(r.plan.decided)}</span>
        <span>target 1 {pct(r.plan.target1RatePct)} · stop {pct(r.plan.stopRatePct)}</span>
        <span>avg R {fixed(r.plan.avgR)}</span>
      </span>
    );
  }
  return r.fade ? <span style={{ ...mono, fontSize: 11.5 }}>faded {pct(r.fade.fadedRatePct)} of {count(r.fade.n)}</span> : <span style={{ color: "var(--cp-ink-3)" }}>—</span>;
}

function OutcomeCard({ r }: { r: OutcomeRow }) {
  return (
    <div data-testid="spt-an-row" data-key={r.key} data-small={r.smallSample ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 8, padding: 12, borderRadius: 12, border: "1px solid var(--cp-line)" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 6 }}>
        <span style={{ fontWeight: 600, overflowWrap: "anywhere", minWidth: 0 }}>{r.key}</span>
        <span className="flex items-center" style={{ gap: 6 }}><span data-testid="spt-an-signals" style={mono}>{count(r.signals)} signals</span><SmallTag on={r.smallSample} note={r.note} /></span>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
        {HORIZONS.map((h) => <div key={h} className="flex min-w-0 flex-col" style={{ gap: 2 }}><span style={{ ...eyebrow, fontSize: 9 }}>{H_LABEL[h]}</span><HorizonCell r={r} h={h} /></div>)}
      </div>
      {(r.plan || r.fade) && <PlanCell r={r} />}
    </div>
  );
}

// ── 2. your paper results ────────────────────────────────────────────────

/** services/spt/paper/orders.py EXIT_REASONS; a code not listed is shown as sent. */
const EXIT_LABEL: Record<string, string> = { stop: "Stop loss", target_1: "Target 1", target_2: "Target 2", trailing: "Trailing stop loss", trend: "Trend exit",
  time: "Time exit", manual: "Closed by you", risk_action: "Risk action", expiry: "Expiry" };

function Kpi({ label, value, sub, testId, color }: { label: string; value: ReactNode; sub?: ReactNode; testId: string; color?: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 3, padding: "10px 12px", borderRadius: 12, border: "1px solid var(--cp-line)" }}>
      <span style={{ ...eyebrow, fontSize: 9.5 }}>{label}</span>
      <span data-testid={testId} style={{ fontFamily: MONO, fontSize: 16, color: color ?? "var(--cp-ink)", overflowWrap: "anywhere" }}>{value}</span>
      {sub && <span style={{ ...quiet, fontSize: 10.5 }}>{sub}</span>}
    </div>
  );
}

function PaperResults({ narrow }: { narrow: boolean }) {
  const q = useSptTrades();
  const trades = q.data?.trades ?? [];
  const s = useMemo(() => resultStats(trades), [trades]);
  const exits = useMemo(() => {
    const m = new Map<string, number>();
    for (const t of trades) m.set(t.exitReason ?? "not recorded", (m.get(t.exitReason ?? "not recorded") ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [trades]);
  const byScanner = useMemo(() => {
    const m = new Map<string, SptTrade[]>();
    for (const t of trades) {
      const ids = [...new Set(t.signalIds.map(scannerOfSignalId).filter((x): x is string => !!x))];
      for (const id of ids.length ? ids : ["(no signal ids on the trade)"]) m.set(id, [...(m.get(id) ?? []), t]);
    }
    return [...m.entries()].map(([k, ts]) => ({ key: k, s: resultStats(ts) })).sort((a, b) => b.s.trades - a.s.trades);
  }, [trades]);

  return (
    <section data-testid="spt-an-results" className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", gap: 12, padding: "16px 16px 14px" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
        <h3 className="cp-eyebrow m-0" style={{ color: "var(--cp-ink-2)" }}>Your paper results from scanner opportunities</h3>
        <span style={{ ...quiet, fontSize: 11 }}>Closed paper trades only · computed on this screen from the trades listed</span>
      </div>
      {q.isError ? <QueryProblem what="Your closed paper trades" error={q.error} onRetry={() => q.refetch()} />
        : q.isPending ? <LoadingBlock label="Reading your closed paper trades" rows={3} />
        : trades.length === 0 ? (
          <div data-testid="spt-an-results-empty" style={quiet}>No closed paper trade from scanner opportunities yet. Results appear here once a paper position opened from an opportunity is closed.</div>
        ) : (
          <>
            <div data-testid="spt-an-kpis" className="grid" style={{ gridTemplateColumns: `repeat(auto-fit,minmax(${narrow ? 140 : 160}px,1fr))`, gap: 8 }}>
              <Kpi label="Trades" value={count(s.trades)} testId="spt-an-trades" sub={`${s.wins} won · ${s.losses} lost${s.flat ? ` · ${s.flat} flat` : ""}`} />
              <Kpi label="Win rate" value={pct(s.winRatePct)} testId="spt-an-winrate" />
              <Kpi label="Average win" value={rupees(s.avgWinRs, true)} testId="spt-an-avgwin" color={signColor(s.avgWinRs)} />
              <Kpi label="Average loss" value={rupees(s.avgLossRs, true)} testId="spt-an-avgloss" color={signColor(s.avgLossRs)} />
              <Kpi label="Expectancy (R)" value={s.expectancyR == null ? "—" : `${s.expectancyR >= 0 ? "+" : "−"}${Math.abs(s.expectancyR).toFixed(2)} R`} testId="spt-an-exp-r" sub={`from ${s.withR} trade${s.withR === 1 ? "" : "s"} with an R`} />
              <Kpi label="Expectancy (₹)" value={rupees(s.expectancyRs, true)} testId="spt-an-exp-rs" color={signColor(s.expectancyRs)} />
              <Kpi label="Profit factor" value={s.profitFactor == null ? "—" : s.profitFactor.toFixed(2)} testId="spt-an-pf" sub={s.profitFactor == null ? "no losing trade yet" : undefined} />
              <Kpi label="Net P&L" value={rupees(s.netRs, true)} testId="spt-an-net" color={signColor(s.netRs)} />
              <Kpi label="Average holding" value={s.avgHoldingDays == null ? "—" : `${s.avgHoldingDays.toFixed(1)} days`} testId="spt-an-hold" sub={`from ${s.withHolding} trade${s.withHolding === 1 ? "" : "s"} with both times`} />
            </div>
            {s.withoutNet > 0 && <span data-testid="spt-an-unpriced" style={{ ...quiet, color: "var(--amber)" }}>{s.withoutNet} closed trade{s.withoutNet === 1 ? " has" : "s have"} no net P&L recorded and {s.withoutNet === 1 ? "is" : "are"} left out of these figures.</span>}
            <ul data-testid="spt-an-formulas" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, ...quiet, fontSize: 11 }}>
              <li>Win rate = trades with a positive net P&amp;L ÷ trades with a net P&amp;L.</li>
              <li>Expectancy (₹) = win rate × average win − loss rate × |average loss|, on net P&amp;L after the paper costs (PRD §13.3).</li>
              <li>Expectancy (R) = the average of each trade’s R multiple (net P&amp;L ÷ its initial risk), as the paper engine recorded it.</li>
              <li>Profit factor = gross profit ÷ |gross loss| (PRD §13.4): {rupees(s.grossProfitRs)} ÷ {rupees(Math.abs(s.grossLossRs))}.</li>
              <li>Average holding = the average of closed time − opened time.</li>
              <li>Paper results on a small number of trades say little; no figure here is a forecast.</li>
            </ul>
            <Section title="Exit reasons" testId="spt-an-exits">
              <div className="flex flex-wrap" style={{ gap: 6 }}>
                {exits.map(([k, n]) => <Pill key={k} tone="ink" attrs={{ "data-reason": k }} testId="spt-an-exit">{EXIT_LABEL[k] ?? k.replace(/_/g, " ")} · {n}</Pill>)}
              </div>
            </Section>
            <Section title="By scanner" testId="spt-an-by-scanner" note="The scanner id is read from each trade’s signal ids; a trade with signals from several scanners counts under each.">
              <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
                {byScanner.map(({ key, s: x }) => (
                  <div key={key} data-testid="spt-an-scanner-row" data-key={key} className="flex flex-wrap items-baseline justify-between" style={{ gap: "2px 12px", padding: "6px 0", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5 }}>
                    <span style={{ overflowWrap: "anywhere", minWidth: 0 }}>{key}</span>
                    <span style={mono}>{x.trades} trade{x.trades === 1 ? "" : "s"} · win {pct(x.winRatePct)} · net <span style={{ color: signColor(x.netRs) }}>{rupees(x.netRs, true)}</span> · {x.expectancyR == null ? "R —" : `${x.expectancyR.toFixed(2)} R`}</span>
                  </div>
                ))}
              </div>
            </Section>
          </>
        )}
    </section>
  );
}
