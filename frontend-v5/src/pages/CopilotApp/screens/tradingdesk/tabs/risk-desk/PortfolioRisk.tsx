/**
 * Risk Desk › Portfolio risk (?tab=risk&view=portfolio) — the open SPT book's risk (PRD §12.4, §19.5; Workflow §19; owner,
 * 5 Nov 2026).
 *
 *   KPI strip               SPT planned vs stressed risk, open risk vs its cap, daily / weekly loss used, drawdown
 *   01 Loss & drawdown      daily and weekly loss utilisation, drawdown and the ladder band   GET /api/v1/risk/account/{id}
 *   02 Risk warnings        what the risk engine states
 *   03 Sector concentration each sector's exposure (vs the sector limit) and its planned / stressed risk
 *                                                     GET /api/v1/risk/exposures/{id} + /risk/stress-test/{id}
 *   04 Stress scenarios     gap through the stop, a sector shock, the market −3 % / −5 %     GET /api/v1/risk/stress-test/{id}
 *   05 Positions at risk    each open SPT position: quantity, stop, current price, risk from the price to the stop
 *                                                     GET /api/v1/paper/positions?status=open
 *   06 Not in this release  correlation matrix (the risk service skips it), F&O Greeks (F&O execution out of scope), margin
 *                           (cash shares only) — said, never drawn with numbers
 */
import { LoadingBlock, Pill } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { QueryProblem } from "../../../trading/parts";
import { stampIst } from "../../overview-data";
import { Card } from "../../RiskControls";
import { Kpi, UseBar, ViewHead, quiet } from "./parts";
import {
  riskBy, riskToStop, useSptExposures, useSptPositions, useSptRiskAccount, useSptStress,
  type SptAccount, type SptPosition, type SptRiskAccount, type SptStress,
} from "./spt-risk-api";
import {
  BandPill, DASH, FigList, FigRow, LadderBands, ModePill, NotAvailable, RowsTable, SourceNote, SptAccountGate, Warnings,
  fig, lossTone, pct2, rs, usedOf, type Col,
} from "./spt-risk-parts";

function headline(a: SptRiskAccount | undefined): string {
  if (!a) return "The open paper book's risk: planned, stressed and by scenario.";
  if (!a.sptRisk) return "The open paper book's risk is unknown: the account could not be read.";
  return `Open planned risk ${rs(a.sptRisk.plannedRs)}, ${rs(a.sptRisk.stressedRs)} if every stop gaps by ${fig(a.sptRisk.stressedGapPct)}%.`;
}

const ofEquity = (v: number | null, eq: number | null) => (v == null || eq == null || eq <= 0 ? DASH : pct2((v / eq) * 100));
/** −5% with a true minus sign; "—" when unknown. */
const signedPct = (v: number | null) => (v == null ? DASH : `${v < 0 ? "−" : ""}${fig(Math.abs(v))}%`);

// ── 01 ───────────────────────────────────────────────────────────────────

function LossAndDrawdown({ a }: { a: SptRiskAccount }) {
  const row = (k: "day" | "week") => {
    const l = k === "day" ? a.dailyLoss : a.weeklyLoss;
    return (
      <FigRow testId={`spt-pr-${k}-loss`} k={k === "day" ? "Daily loss utilisation" : "Weekly loss utilisation"} v={usedOf(l.lossPct, l.limitPct)}
        tone={lossTone(l.lossPct, l.limitPct)}
        note={<>
          <UseBar used={l.lossPct} limit={l.limitPct} label={k === "day" ? "Daily loss" : "Weekly loss"} />
          <span style={{ display: "block", marginTop: 4 }}>{l.pnlRs == null ? "P&L unknown — new positions are blocked (fail closed)." : `P&L ${rs(l.pnlRs)}${l.breached ? " — at or past the limit" : ""}`}</span>
        </>} />
    );
  };
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <FigList testId="spt-pr-loss">
        {row("day")}
        {row("week")}
        <FigRow testId="spt-pr-drawdown" k="Drawdown from peak" v={pct2(a.drawdown.pct)} tone={lossTone(a.drawdown.pct, a.drawdown.profileHaltPct)}
          note={`peak ${rs(a.drawdown.peakRs)}; the risk profile halts at ${a.drawdown.profileHaltPct == null ? DASH : `${fig(a.drawdown.profileHaltPct)}%`}`} />
      </FigList>
      <LadderBands ladder={a.drawdown.ladder} testId="spt-pr-ladder" />
    </div>
  );
}

// ── 02 ───────────────────────────────────────────────────────────────────

interface SectorRow { sector: string; exposureRs: number | null; pctOfEquity: number | null; limitPct: number | null; plannedRs: number | null; stressedRs: number | null }

function Sectors({ acc, stress }: { acc: SptAccount; stress: SptStress | undefined }) {
  const ex = useSptExposures(acc.accountId);
  const risk = new Map(riskBy(stress?.positions ?? [], "sector").map((r) => [r.key, r]));
  const rows: SectorRow[] = (ex.data?.bySector ?? []).map((s) => ({
    sector: s.key, exposureRs: s.exposureRs, pctOfEquity: s.pctOfEquity, limitPct: s.limitPct,
    plannedRs: risk.get(s.key)?.plannedRs ?? null, stressedRs: risk.get(s.key)?.stressedRs ?? null,
  }));
  for (const [k, r] of risk) {
    if (!rows.some((x) => x.sector === k)) rows.push({ sector: k, exposureRs: null, pctOfEquity: null, limitPct: null, plannedRs: r.plannedRs, stressedRs: r.stressedRs });
  }
  const cols: Col<SectorRow>[] = [
    { key: "sector", head: "Sector", cell: (r) => r.sector },
    { key: "exposure", head: "Exposure", num: true, cell: (r) => rs(r.exposureRs) },
    { key: "pct", head: "% of equity", num: true, cell: (r) => pct2(r.pctOfEquity) },
    { key: "limit", head: "Limit", num: true, cell: (r) => (r.limitPct == null ? DASH : `${fig(r.limitPct)}%`) },
    { key: "use", head: "Use", cell: (r) => <span style={{ display: "block", minWidth: 60 }}><UseBar used={r.pctOfEquity} limit={r.limitPct} label={`${r.sector} exposure`} /></span> },
    { key: "planned", head: "Planned risk", num: true, cell: (r) => (r.plannedRs == null ? DASH : rs(r.plannedRs)) },
    { key: "stressed", head: "Stressed risk", num: true, cell: (r) => (r.stressedRs == null ? DASH : rs(r.stressedRs)) },
  ];
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      {ex.isPending && <LoadingBlock label="Reading your sector exposure" rows={2} />}
      {ex.isError && <div data-testid="spt-pr-sectors-error"><QueryProblem what="Your sector exposure" error={ex.error} onRetry={() => { void ex.refetch(); }} /></div>}
      {ex.data && <RowsTable rows={rows} cols={cols} rowKey={(r) => r.sector} testId="spt-pr-sectors" empty="No open sector exposure." />}
      {ex.data?.unclassifiedRs != null && ex.data.unclassifiedRs > 0 && (
        <span data-testid="spt-pr-unclassified" style={quiet}>{rs(ex.data.unclassifiedRs)} has no sector on record and counts against every sector's limit.</span>
      )}
      <SourceNote testId="spt-pr-sectors-basis">Exposure covers every paper position and pending entry (risk book); planned and stressed risk cover the open SPT entries (stress test). A dash means the source has no figure for that sector.</SourceNote>
    </div>
  );
}

// ── 03 ───────────────────────────────────────────────────────────────────

interface Scenario { key: string; name: string; planned: number | null; loss: number | null; worst: string | null; text: string | null }

function scenariosOf(s: SptStress): Scenario[] {
  const out: Scenario[] = [];
  if (s.gap) out.push({ key: "gap", name: `Gap through stop (${fig(s.gap.gapPct)}%)`, planned: s.gap.plannedRs, loss: s.gap.stressedRs, worst: null, text: s.gap.text });
  if (s.sector) out.push({ key: "sector", name: `Sector shock (${signedPct(s.sector.shockPct)})`, planned: null, loss: s.sector.worstLossRs, worst: s.sector.worstSector, text: s.sector.text });
  for (const m of s.market?.results ?? []) {
    out.push({ key: `market${m.shockPct}`, name: `Market ${signedPct(m.shockPct)}`, planned: null, loss: m.lossRs, worst: null,
      text: `${s.market?.text ?? ""}${m.betaAssumed ? ` Beta ${fig(m.beta)} assumed.` : ""}`.trim() || null });
  }
  return out;
}

function Scenarios({ q, equity }: { q: ReturnType<typeof useSptStress>; equity: number | null }) {
  const s = q.data;
  const cols: Col<Scenario>[] = [
    { key: "name", head: "Scenario", cell: (r) => r.name },
    { key: "planned", head: "Planned loss", num: true, cell: (r) => (r.planned == null ? DASH : rs(r.planned)) },
    { key: "loss", head: "Stressed / scenario loss", num: true, cell: (r) => rs(r.loss) },
    { key: "pct", head: "% of equity", num: true, cell: (r) => ofEquity(r.loss, equity) },
    { key: "worst", head: "Worst sector", cell: (r) => r.worst ?? DASH },
    { key: "text", head: "What it assumes", cell: (r) => <span style={{ display: "block", maxWidth: 340, overflowWrap: "anywhere", fontSize: 12.5, color: "var(--cp-ink-2)" }}>{r.text ?? DASH}</span> },
  ];
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      {q.isPending && <LoadingBlock label="Running the stress scenarios" rows={3} />}
      {q.isError && <div data-testid="spt-pr-stress-error"><QueryProblem what="The stress test" error={q.error} onRetry={() => { void q.refetch(); }} /></div>}
      {s && (
        <>
          <RowsTable rows={scenariosOf(s)} cols={cols} rowKey={(r) => r.key} testId="spt-pr-scenarios" empty="The API sent no scenarios." />
          {s.sector && s.sector.bySectorRs.length > 0 && (
            <span data-testid="spt-pr-sector-shock" style={{ ...quiet, overflowWrap: "anywhere" }}>
              Sector shock by sector: {s.sector.bySectorRs.map((x) => `${x.sector} ${rs(x.lossRs)}`).join(" · ")}.
            </span>
          )}
          {s.unpriced.length > 0 && (
            <span data-testid="spt-pr-unpriced" style={{ ...quiet, color: "var(--amber)" }}>
              {s.unpriced.length} {s.unpriced.length === 1 ? "entry is" : "entries are"} not priced yet (no quantity, price or stop) and left out of every total.
            </span>
          )}
          <SourceNote testId="spt-pr-stress-basis">
            {fig(s.positions.length, 0)} open SPT {s.positions.length === 1 ? "entry" : "entries"}, value {rs(s.totals.valueRs)}. {s.basis ?? ""} {s.version ? `(${s.version})` : ""}
          </SourceNote>
        </>
      )}
    </div>
  );
}

// ── 04 ───────────────────────────────────────────────────────────────────

function Positions() {
  const q = useSptPositions("open");
  const rows = (q.data?.items ?? []).filter((p) => p.isOpen)
    .sort((x, y) => (riskToStop(y) ?? -1) - (riskToStop(x) ?? -1));
  const cols: Col<SptPosition>[] = [
    { key: "symbol", head: "Symbol", cell: (p) => p.symbol ?? DASH },
    { key: "qty", head: "Quantity", num: true, cell: (p) => fig(p.quantity, 0) },
    { key: "avg", head: "Average price", num: true, cell: (p) => fig(p.avgEntryPrice) },
    { key: "stop", head: "Stop", num: true, cell: (p) => fig(p.stopLoss) },
    { key: "price", head: "Current price", num: true, cell: (p) => (p.mark?.price == null ? `${DASH} (no live mark)` : `${fig(p.mark.price)}${p.mark.basis ? ` · ${p.mark.basis}` : ""}`) },
    { key: "risk", head: "Risk to stop now", num: true, cell: (p) => {
      const r = riskToStop(p);
      return r == null ? (p.stopLoss == null ? `${DASH} (no stop)` : `${DASH} (no live mark)`) : rs(r);
    } },
    { key: "riskEntry", head: "Risk at stop from cost", num: true, cell: (p) => rs(p.riskAtStopRs) },
    { key: "state", head: "State", cell: (p) => (p.state ? p.state.replace(/_/g, " ").toLowerCase() : DASH) },
  ];
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      {q.isPending && <LoadingBlock label="Reading your open positions" rows={2} />}
      {q.isError && <div data-testid="spt-pr-positions-error"><QueryProblem what="Your open positions" error={q.error} onRetry={() => { void q.refetch(); }} /></div>}
      {q.data && <RowsTable rows={rows} cols={cols} rowKey={(p) => p.positionId} testId="spt-pr-positions" empty="No open SPT paper positions." />}
      <SourceNote testId="spt-pr-positions-basis">Risk to stop now = (current price − stop) × quantity, floored at zero; the current price is the position's live mark (bid, else last traded price). Without a live mark it is not estimated.</SourceNote>
    </div>
  );
}

// ── the view ─────────────────────────────────────────────────────────────

function Body({ acc }: { acc: SptAccount }) {
  const { mobile } = useCopilotShell();
  const q = useSptRiskAccount(acc.accountId);
  const stress = useSptStress(acc.accountId);
  const a = q.data;
  return (
    <>
      <ViewHead view="Portfolio risk" title={headline(a)} />
      {a && (
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <ModePill mode={a.mode ?? acc.mode} />
          <BandPill band={a.drawdown.ladder.band} />
          {a.asOf && <span className="cp-mono-note">as of {stampIst(a.asOf) ?? a.asOf} · refreshed every 30 s</span>}
        </span>
      )}
      {q.isPending && <LoadingBlock label="Reading your account's risk" rows={4} />}
      {q.isError && <div data-testid="spt-pr-error"><QueryProblem what="Your account's risk" error={q.error} onRetry={() => { void q.refetch(); }} /></div>}
      {a && (
        <>
          <div className="grid" style={{ gap: 10, gridTemplateColumns: `repeat(auto-fit,minmax(min(100%,${mobile ? 140 : 160}px),1fr))` }}>
            <Kpi k="Open planned risk" testId="spt-pr-kpi-planned" value={rs(a.sptRisk?.plannedRs)} note={`${ofEquity(a.sptRisk?.plannedRs ?? null, a.equityRs)} of equity`} />
            <Kpi k="Stressed risk" testId="spt-pr-kpi-stressed" value={rs(a.sptRisk?.stressedRs)} note={`${ofEquity(a.sptRisk?.stressedRs ?? null, a.equityRs)} of equity`} />
            <Kpi k="Open risk vs limit" testId="spt-pr-kpi-open" value={pct2(a.openRisk.usedPctOfEquity)} tone={lossTone(a.openRisk.usedPctOfEquity, a.openRisk.limitPct)}
              note={`limit ${a.openRisk.limitPct == null ? DASH : `${fig(a.openRisk.limitPct)}%`} · ${rs(a.openRisk.rs)} of ${rs(a.openRisk.capRs)}`} />
            <Kpi k="Daily loss" testId="spt-pr-kpi-day" value={pct2(a.dailyLoss.lossPct)} tone={lossTone(a.dailyLoss.lossPct, a.dailyLoss.limitPct)} note={`limit ${a.dailyLoss.limitPct == null ? DASH : `${fig(a.dailyLoss.limitPct)}%`}`} />
            <Kpi k="Weekly loss" testId="spt-pr-kpi-week" value={pct2(a.weeklyLoss.lossPct)} tone={lossTone(a.weeklyLoss.lossPct, a.weeklyLoss.limitPct)} note={`limit ${a.weeklyLoss.limitPct == null ? DASH : `${fig(a.weeklyLoss.limitPct)}%`}`} />
            <Kpi k="Drawdown" testId="spt-pr-kpi-drawdown" value={pct2(a.drawdown.pct)} tone={lossTone(a.drawdown.pct, a.drawdown.profileHaltPct)} note={`band ${a.drawdown.ladder.band ?? "unknown"}`} />
          </div>
          <div className="grid" style={{ gap: mobile ? 14 : 18, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", alignItems: "start" }}>
            <Card id="spt-pr-loss" num="01" title="Loss utilisation & drawdown" testId="spt-pr-loss-card"><LossAndDrawdown a={a} /></Card>
            <Card id="spt-pr-warn" num="02" title="Active risk warnings" testId="spt-pr-warn-card"><Warnings a={a} testId="spt-pr-warnings" /></Card>
          </div>
          <Card id="spt-pr-sectors" num="03" title="Sector concentration" testId="spt-pr-sectors-card"><Sectors acc={acc} stress={stress.data} /></Card>
        </>
      )}
      <Card id="spt-pr-stress" num="04" title="Stress scenarios" testId="spt-pr-stress-card"><Scenarios q={stress} equity={a?.equityRs ?? stress.data?.equityRs ?? null} /></Card>
      <Card id="spt-pr-positions" num="05" title="Positions at risk" testId="spt-pr-positions-card"><Positions /></Card>
      <Card id="spt-pr-na" num="06" title="Not in this release" testId="spt-pr-na-card">
        <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
          <NotAvailable testId="spt-pr-na-correlation" title="Correlation matrix"
            why="The risk service skips the correlation check in this release (no point-in-time return correlation is computed), so no matrix is drawn. Sector exposure above is the concentration control." />
          <NotAvailable testId="spt-pr-na-greeks" title="F&O Greeks"
            why="F&O execution is out of scope in this release: scanner-to-paper trading trades cash shares only, so there are no option positions to take Greeks of." />
          <NotAvailable testId="spt-pr-na-margin" title="Margin utilisation"
            why="Cash shares only, paid in full from paper cash: no margin is used, so there is nothing to measure." />
        </div>
      </Card>
      <span data-testid="spt-pr-paper-only" className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Pill tone="mint">Paper only</Pill>
        <span style={quiet}>Nothing here is sent to a broker. Real holdings are not counted.</span>
      </span>
    </>
  );
}

export function PortfolioRisk() {
  const { mobile } = useCopilotShell();
  return (
    <div data-testid="spt-portfolio-view" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <SptAccountGate head={<ViewHead view="Portfolio risk" title={headline(undefined)} />}>{(acc) => <Body acc={acc} />}</SptAccountGate>
    </div>
  );
}
