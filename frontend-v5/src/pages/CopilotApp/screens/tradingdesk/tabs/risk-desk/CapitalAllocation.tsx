/**
 * Risk Desk › Capital allocation (?tab=risk&view=allocation) — capital and risk side by side (PRD §12.3, §19.4; Workflow §9,
 * §18; owner, 5 Nov 2026). The screen keeps the two apart: capital is the rupees put to work, risk is what the open
 * positions could lose at their stops — a small capital allocation can still carry large risk (PRD §12.3).
 *
 *   KPI strip              account capital, available, in use (deployed + reserved), the unallocated reserve, risk budget left
 *   01 Capital allocation  each bucket's cap vs used (equity positional / intraday / F&O) and the reserve; exposure by sector
 *                          and by instrument                       GET /api/v1/risk/exposures/{id} + /risk/account/{id}
 *   02 Risk allocation     open risk vs its budget, SPT planned vs stressed, risk by sector and by instrument (the stress
 *                          test's open entries)                     GET /api/v1/risk/stress-test/{id}
 *   03 Ranked opportunities QUALIFIED opportunities in rank order, each sized by your limits now: quantity, capital, planned
 *                          risk and why it would be reduced or not fit  GET /api/v1/allocation/recommendations/{id}
 *   04 Recalculate         POST /api/v1/allocation/recalculate/{id}: re-sizes only your proposals awaiting approval; shows
 *                          each one's quantity before → after. Nothing is ordered.
 */
import { useState } from "react";
import { Btn, LoadingBlock, Pill, type Tone } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { QueryProblem } from "../../../trading/parts";
import { stampIst } from "../../overview-data";
import { Card } from "../../RiskControls";
import { Kpi, UseBar, ViewHead, quiet } from "./parts";
import {
  riskBy, useSptAwaiting, useSptExposures, useSptRanked, useSptRecalculate, useSptRiskAccount, useSptStress,
  type SptAccount, type SptProposalBrief, type SptRankedItem, type SptRecalc, type SptRiskAccount,
} from "./spt-risk-api";
import { DASH, FigList, FigRow, ModePill, RowsTable, SourceNote, SptAccountGate, fig, lossTone, pct2, rs, type Col } from "./spt-risk-parts";

export const BUCKET_LABEL: Record<string, string> = {
  equity_positional: "Equity positional", equity_intraday: "Equity intraday", fno: "F&O strategies", reserve: "Unallocated reserve",
};
const DECISION: Record<string, { word: string; tone: Tone }> = {
  ALLOCATION_APPROVED: { word: "fits in full", tone: "mint" },
  ALLOCATION_REDUCED: { word: "reduced", tone: "amber" },
  ALLOCATION_REJECTED: { word: "does not fit", tone: "danger" },
};
const OUTCOME: Record<string, string> = { not_tradable: "tracked, not traded", rejected: "fails the plan checks" };

const sub = { fontSize: 12.5, fontWeight: 600, color: "var(--cp-ink-2)", margin: "6px 0 0" } as const;

function headline(a: SptRiskAccount | undefined): string {
  if (!a) return "Capital and risk, allocated separately.";
  const inUse = a.deployedRs == null && a.reservedRs == null ? null : (a.deployedRs ?? 0) + (a.reservedRs ?? 0);
  const cap = inUse == null || a.equityRs == null ? "Capital in use is unknown" : `${rs(inUse)} of ${rs(a.equityRs)} capital in use`;
  const risk = a.openRisk.rs == null || a.openRisk.capRs == null ? "the risk budget is unknown" : `${rs(a.openRisk.rs)} of the ${rs(a.openRisk.capRs)} risk budget used`;
  return `${cap}; ${risk}.`;
}

// ── 01 capital ───────────────────────────────────────────────────────────

function CapitalSide({ acc, a }: { acc: SptAccount; a: SptRiskAccount }) {
  const ex = useSptExposures(acc.accountId);
  const e = ex.data;
  const buckets = e?.byCategory.length
    ? e.byCategory
    : Object.entries(a.utilisation.buckets).map(([k, v]) => ({ category: k, usedRs: v.usedRs, capRs: v.capRs, bucketPct: a.limits.bucketsPct[k] ?? null }));
  const reservePct = a.limits.bucketsPct.reserve ?? acc.bucketsPct.reserve ?? null;
  type B = (typeof buckets)[number];
  const bucketCols: Col<B>[] = [
    { key: "bucket", head: "Bucket", cell: (b) => BUCKET_LABEL[b.category] ?? b.category },
    { key: "pct", head: "Share", num: true, cell: (b) => (b.bucketPct == null ? DASH : `${fig(b.bucketPct)}%`) },
    { key: "cap", head: "Cap", num: true, cell: (b) => rs(b.capRs) },
    { key: "used", head: "Used", num: true, cell: (b) => rs(b.usedRs) },
    { key: "left", head: "Left", num: true, cell: (b) => (b.capRs == null || b.usedRs == null ? DASH : rs(b.capRs - b.usedRs)) },
    { key: "bar", head: "Use", cell: (b) => <span style={{ display: "block", minWidth: 60 }}><UseBar used={b.usedRs} limit={b.capRs} label={BUCKET_LABEL[b.category] ?? b.category} /></span> },
  ];
  type X = NonNullable<typeof e>["bySector"][number];
  const exCols = (head: string): Col<X>[] => [
    { key: "name", head, cell: (r) => r.key },
    { key: "exposure", head: "Exposure", num: true, cell: (r) => rs(r.exposureRs) },
    { key: "pct", head: "% of equity", num: true, cell: (r) => pct2(r.pctOfEquity) },
    { key: "limit", head: "Limit", num: true, cell: (r) => (r.limitPct == null ? DASH : `${fig(r.limitPct)}%`) },
  ];
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <span className="cp-eyebrow">Capital — the rupees put to work</span>
      <p style={sub}>By bucket</p>
      <RowsTable rows={buckets} cols={bucketCols} rowKey={(b) => b.category} testId="spt-al-buckets" empty="No bucket figures were sent." />
      <FigList>
        <FigRow testId="spt-al-reserve" k="Unallocated reserve" v={rs(a.reserveBucketRs)}
          note={`${reservePct == null ? DASH : `${fig(reservePct)}%`} of equity, never allocated to a new position`} />
      </FigList>
      {ex.isPending && <LoadingBlock label="Reading your exposures" rows={2} />}
      {ex.isError && <div data-testid="spt-al-exposures-error"><QueryProblem what="Your exposures" error={ex.error} onRetry={() => { void ex.refetch(); }} /></div>}
      {e && (
        <>
          <p style={sub}>By sector</p>
          <RowsTable rows={e.bySector} cols={exCols("Sector")} rowKey={(r) => r.key} testId="spt-al-sectors" empty="No open sector exposure." />
          {e.unclassifiedRs != null && e.unclassifiedRs > 0 && (
            <span data-testid="spt-al-unclassified" style={quiet}>Plus {rs(e.unclassifiedRs)} with no sector on record (counted against every sector's limit).</span>
          )}
          <p style={sub}>By instrument</p>
          <RowsTable rows={e.byInstrument} cols={exCols("Instrument")} rowKey={(r) => r.key} testId="spt-al-instruments" empty="No open positions or pending entries." />
          <SourceNote testId="spt-al-capital-basis">Total exposure {rs(e.totalRs)}. {e.basis ?? ""}</SourceNote>
        </>
      )}
    </div>
  );
}

// ── 02 risk ──────────────────────────────────────────────────────────────

function RiskSide({ acc, a }: { acc: SptAccount; a: SptRiskAccount }) {
  const st = useSptStress(acc.accountId);
  const s = st.data;
  const left = a.openRisk.capRs == null || a.openRisk.rs == null ? null : a.openRisk.capRs - a.openRisk.rs;
  type R = ReturnType<typeof riskBy>[number];
  const cols = (head: string): Col<R>[] => [
    { key: "name", head, cell: (r) => r.key },
    { key: "planned", head: "Planned risk", num: true, cell: (r) => rs(r.plannedRs) },
    { key: "stressed", head: "Stressed risk", num: true, cell: (r) => rs(r.stressedRs) },
    { key: "share", head: "Share of stressed", num: true, cell: (r) => (s?.totals.stressedRs ? pct2((r.stressedRs / s.totals.stressedRs) * 100) : DASH) },
  ];
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <span className="cp-eyebrow">Risk — what the open positions could lose at their stops</span>
      <FigList testId="spt-al-risk-figs">
        <FigRow testId="spt-al-risk-budget" k="Open risk vs budget" v={`${rs(a.openRisk.rs)} of ${rs(a.openRisk.capRs)}`} tone={lossTone(a.openRisk.rs, a.openRisk.capRs)}
          note={<>
            <UseBar used={a.openRisk.rs} limit={a.openRisk.capRs} label="Open risk budget" />
            <span style={{ display: "block", marginTop: 4 }}>{left == null ? "Budget left unknown." : `${rs(Math.max(0, left))} of risk budget left`} (limit {a.openRisk.limitPct == null ? DASH : `${fig(a.openRisk.limitPct)}%`} of equity).</span>
          </>} />
        <FigRow testId="spt-al-planned" k="SPT planned risk" v={rs(a.sptRisk?.plannedRs)} />
        <FigRow testId="spt-al-stressed" k="SPT stressed risk" v={rs(a.sptRisk?.stressedRs)}
          note={a.sptRisk ? `with a ${fig(a.sptRisk.stressedGapPct)}% gap through every stop` : "not sent"} />
      </FigList>
      {st.isPending && <LoadingBlock label="Reading the stress test" rows={2} />}
      {st.isError && <div data-testid="spt-al-stress-error"><QueryProblem what="The risk by position" error={st.error} onRetry={() => { void st.refetch(); }} /></div>}
      {s && (
        <>
          <p style={sub}>Risk by sector</p>
          <RowsTable rows={riskBy(s.positions, "sector")} cols={cols("Sector")} rowKey={(r) => r.key} testId="spt-al-risk-sectors" empty="No open SPT entries carry risk." />
          <p style={sub}>Risk by instrument</p>
          <RowsTable rows={riskBy(s.positions, "symbol")} cols={cols("Instrument")} rowKey={(r) => r.key} testId="spt-al-risk-instruments" empty="No open SPT entries carry risk." />
          <SourceNote testId="spt-al-risk-basis">Risk per entry = quantity × (entry − stop) + round-trip costs; stressed adds the gap. The API reports capital per bucket, not risk per bucket.</SourceNote>
        </>
      )}
    </div>
  );
}

// ── 03 ranked opportunities ──────────────────────────────────────────────

const qtyOf = (r: SptRankedItem) => r.allocation?.quantity ?? r.sizing?.quantity ?? null;
/** A figure as allocated: the allocation's own, ₹0 when no share fits (nothing is allocated); a sized-only row (no allocation
 *  ran because sizing left zero) is ₹0; a row that was never sized (plan checks failed) is unknown. Never pro-rated. */
function allocated(r: SptRankedItem, k: "capitalRs" | "stressedRiskRs"): number | null {
  if (r.allocation) return r.allocation[k] ?? (r.allocation.quantity === 0 ? 0 : null);
  if (r.sizing) return r.sizing.quantity === 0 ? 0 : null;
  return null;
}

function reasonOf(r: SptRankedItem): string {
  const parts = [
    ...(r.allocation?.reasons.map((x) => x.message) ?? []),
    ...(r.sizing?.blocked.map((x) => x.message) ?? []),
    ...(r.outcome && r.outcome !== "ok" ? r.explanations : []),
  ];
  if (parts.length) return parts.join(" ");
  if (r.outcome === "ok" && r.sizing && (r.sizing.quantity ?? 0) < 1) return "The sizing left no whole share.";
  return DASH;
}

function DecisionCell({ r }: { r: SptRankedItem }) {
  if (r.outcome && r.outcome !== "ok") return <span data-decision={r.outcome}><Pill tone="ink">{OUTCOME[r.outcome] ?? r.outcome}</Pill></span>;
  const d = r.allocation?.decision;
  if (!d) return <span data-decision="none"><Pill tone="ink">{r.sizing ? "sized to zero" : "not sized"}</Pill></span>;
  const x = DECISION[d] ?? { word: d, tone: "ink" as Tone };
  return <span data-decision={d}><Pill tone={x.tone}>{x.word}</Pill></span>;
}

function Ranked({ acc }: { acc: SptAccount }) {
  const q = useSptRanked(acc.accountId);
  const cols: Col<SptRankedItem>[] = [
    { key: "rank", head: "Rank", num: true, cell: (r) => fig(r.rank, 0) },
    { key: "symbol", head: "Symbol", cell: (r) => r.symbol ?? DASH },
    { key: "score", head: "Opportunity score", num: true, cell: (r) => fig(r.opportunityScore, 1) },
    { key: "rr", head: "R:R", num: true, cell: (r) => (r.rrT2 == null ? DASH : `${fig(r.rrT2)} : 1`) },
    { key: "qty", head: "Quantity", num: true, cell: (r) => {
      const qn = qtyOf(r);
      const req = r.allocation?.requestedQty;
      return req != null && qn != null && req !== qn ? `${fig(qn, 0)} (sized ${fig(req, 0)})` : fig(qn, 0);
    } },
    { key: "capital", head: "Capital, as allocated", num: true, cell: (r) => rs(allocated(r, "capitalRs")) },
    { key: "planned", head: "Planned risk, as sized", num: true, cell: (r) => rs(r.sizing?.plannedRiskRs ?? null) },
    { key: "stressed", head: "Stressed risk, as allocated", num: true, cell: (r) => rs(allocated(r, "stressedRiskRs")) },
    { key: "decision", head: "Allocation", cell: (r) => <DecisionCell r={r} /> },
    { key: "reason", head: "Why reduced or not fitting", cell: (r) => <span style={{ display: "block", maxWidth: 300, overflowWrap: "anywhere", fontSize: 12.5, color: "var(--cp-ink-2)" }}>{reasonOf(r)}</span> },
    { key: "proposal", head: "Your proposal", cell: (r) => (r.proposal?.state ? r.proposal.state.replace(/_/g, " ").toLowerCase() : "none yet") },
  ];
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      {q.isPending && <LoadingBlock label="Ranking the qualified opportunities" rows={3} />}
      {q.isError && <div data-testid="spt-al-ranked-error"><QueryProblem what="The ranked opportunities" error={q.error} onRetry={() => { void q.refetch(); }} /></div>}
      {q.data && (
        <>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <ModePill mode={q.data.mode} />
            {q.data.asOf && <span className="cp-mono-note">as of {stampIst(q.data.asOf) ?? q.data.asOf}</span>}
          </span>
          <RowsTable rows={q.data.items} cols={cols} rowKey={(r, i) => r.opportunityId ?? `${r.symbol}-${i}`} testId="spt-al-ranked"
            empty="No qualified opportunities right now, so nothing is ranked." />
          <SourceNote testId="spt-al-ranked-basis">
            Ranked by {q.data.rankBasis ?? "a basis the API did not send"}. Quantities are sized by your limits against the account as it stands, in rank
            order, each one taking room from the next. Planned risk is the sizing's (before the allocation caps); capital and stressed risk are what
            the allocation kept. Nothing here is ordered; it changes nothing.
          </SourceNote>
        </>
      )}
    </div>
  );
}

// ── 04 recalculate ───────────────────────────────────────────────────────

function Recalculate({ acc }: { acc: SptAccount }) {
  const awaiting = useSptAwaiting();
  const m = useSptRecalculate(acc.accountId);
  const [before, setBefore] = useState<Record<string, SptProposalBrief>>({});
  const [result, setResult] = useState<SptRecalc | null>(null);
  const n = awaiting.data?.count ?? null;
  const run = () => {
    setBefore(Object.fromEntries((awaiting.data?.items ?? []).map((p) => [p.proposalId, p])));
    m.mutate(undefined, { onSuccess: (r) => setResult(r) });
  };
  type Row = SptRecalc["rows"][number];
  const was = (r: Row) => {
    const b = r.proposalId ? before[r.proposalId] : undefined;
    return b ? b.allocatedQty ?? b.sizedQty : null;
  };
  const cols: Col<Row>[] = [
    { key: "rank", head: "Rank", num: true, cell: (r) => fig(r.rank, 0) },
    { key: "symbol", head: "Symbol", cell: (r) => r.symbol ?? DASH },
    { key: "before", head: "Quantity before", num: true, cell: (r) => fig(was(r), 0) },
    { key: "after", head: "Quantity now", num: true, cell: (r) => fig(r.allocatedQty ?? r.quantity, 0) },
    { key: "change", head: "Change", cell: (r) => {
      const b = was(r);
      const a = r.allocatedQty ?? r.quantity;
      return b == null || a == null ? DASH : a === b ? "unchanged" : a > b ? `+${fig(a - b, 0)}` : `−${fig(b - a, 0)}`;
    } },
    { key: "decision", head: "Allocation", cell: (r) => (r.allocation ? DECISION[r.allocation]?.word ?? r.allocation : "sized to zero") },
    { key: "recorded", head: "Recorded", cell: (r) => (r.recorded == null ? DASH : r.recorded ? "yes" : "no (the proposal moved on)") },
  ];
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <p className="m-0" style={{ fontSize: 13.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        Re-sizes only your proposals awaiting approval ({awaiting.isPending ? "…" : n == null ? DASH : n} now) against the account as it stands, in rank
        order. It records the new quantities on them; nothing is ordered, and the risk check runs again when you approve.
      </p>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Btn type="button" data-testid="spt-al-recalc" onClick={run} disabled={m.isPending}>{m.isPending ? "Recalculating…" : "Recalculate"}</Btn>
        {result?.asOf && <span className="cp-mono-note" data-testid="spt-al-recalc-asof">recalculated {stampIst(result.asOf) ?? result.asOf}</span>}
      </span>
      {m.isError && <div data-testid="spt-al-recalc-error"><QueryProblem what="The recalculation" error={m.error} onRetry={run} /></div>}
      {result && (
        <RowsTable rows={result.rows} cols={cols} rowKey={(r, i) => r.proposalId ?? String(i)} testId="spt-al-recalc-rows"
          empty="No proposals were awaiting your approval, so nothing changed." />
      )}
    </div>
  );
}

// ── the view ─────────────────────────────────────────────────────────────

function Body({ acc }: { acc: SptAccount }) {
  const { mobile } = useCopilotShell();
  const q = useSptRiskAccount(acc.accountId);
  const a = q.data;
  const inUse = a && (a.deployedRs != null || a.reservedRs != null) ? (a.deployedRs ?? 0) + (a.reservedRs ?? 0) : null;
  const left = a && a.openRisk.capRs != null && a.openRisk.rs != null ? Math.max(0, a.openRisk.capRs - a.openRisk.rs) : null;
  return (
    <>
      <ViewHead view="Capital allocation" title={headline(a)} />
      {q.isPending && <LoadingBlock label="Reading your account" rows={4} />}
      {q.isError && <div data-testid="spt-al-error"><QueryProblem what="Your account's capital and risk" error={q.error} onRetry={() => { void q.refetch(); }} /></div>}
      {a && (
        <>
          <div className="grid" style={{ gap: 10, gridTemplateColumns: `repeat(auto-fit,minmax(min(100%,${mobile ? 140 : 170}px),1fr))` }}>
            <Kpi k="Account capital" testId="spt-al-kpi-equity" value={rs(a.equityRs)} note="paper equity" />
            <Kpi k="Available" testId="spt-al-kpi-available" value={rs(a.availableRs)} note="cash not blocked" />
            <Kpi k="Capital in use" testId="spt-al-kpi-inuse" value={rs(inUse)} note={`deployed ${rs(a.deployedRs)} + reserved ${rs(a.reservedRs)}`} />
            <Kpi k="Unallocated reserve" testId="spt-al-kpi-reserve" value={rs(a.reserveBucketRs)} note="never allocated" />
            <Kpi k="Risk budget left" testId="spt-al-kpi-risk-left" value={rs(left)} tone={lossTone(a.openRisk.rs, a.openRisk.capRs)}
              note={`open risk ${rs(a.openRisk.rs)} of ${rs(a.openRisk.capRs)}`} />
          </div>
          <div className="grid" style={{ gap: mobile ? 14 : 18, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", alignItems: "start" }}>
            <Card id="spt-al-capital" num="01" title="Capital allocation" testId="spt-al-capital"><CapitalSide acc={acc} a={a} /></Card>
            <Card id="spt-al-risk" num="02" title="Risk allocation" testId="spt-al-risk"><RiskSide acc={acc} a={a} /></Card>
          </div>
        </>
      )}
      <Card id="spt-al-ranked" num="03" title="Ranked opportunities — sized by your limits" testId="spt-al-ranked-card"><Ranked acc={acc} /></Card>
      <Card id="spt-al-recalc" num="04" title="Recalculate your proposals" testId="spt-al-recalc-card"><Recalculate acc={acc} /></Card>
    </>
  );
}

export function CapitalAllocation() {
  const { mobile } = useCopilotShell();
  return (
    <div data-testid="spt-allocation-view" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <SptAccountGate head={<ViewHead view="Capital allocation" title={headline(undefined)} />}>{(acc) => <Body acc={acc} />}</SptAccountGate>
    </div>
  );
}
