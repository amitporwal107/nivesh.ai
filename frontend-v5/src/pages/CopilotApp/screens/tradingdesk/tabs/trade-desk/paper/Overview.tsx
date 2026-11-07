/**
 * Paper Trading v2 › 01 Overview (?tab=trade&view=paper&sub=overview) — the owner's design of 5 Nov 2026
 * (docs/scanner_paper_trading/UI_DESIGN_V2.md §2 "01 Overview"). Test cases PV2-A-20 … A-27 (test_reports/paper_v2_ui_a_TESTCASES.md).
 *
 *   header      eyebrow "Trading overview"; the synthesis headline built from `headline` by a fixed template (never an LLM),
 *               its concentration span in amber; the prose line "{signals} scanner signals consolidated into {opps} …"
 *   KPI tiles   Account equity · Daily P&L · Capital deployed · Open planned risk · Drawdown · Positions (`kpis`)
 *   pipeline    "Today's pipeline · signal → position": six stages, bar widths relative to scanner signals
 *   warnings    "Risk warnings": dot by level, title, mono "CODE · HH:MM"; mint lines (e.g. "All feeds healthy") last
 *
 * One read: GET /api/v1/paper/overview (api-a.ts usePaperOverview, shared with the shell's status strip). A null figure
 * reads "—", never 0; every empty state says what is missing. Paper only.
 */
import { LoadingBlock, fmtINR } from "../../../../../components/ui";
import { QueryProblem } from "../../../../trading/parts";
import { useNarrow } from "../spt-parts";
import { PIPELINE_STAGES, usePaperOverview, type PaperHeadline, type PaperKpis, type PaperOverview, type PaperWarning, type PipelineStage } from "./api-a";
import { Card, Dot, Kpi, KpiGrid, Note, SectionHeader, ShareBar, Split, levelOf, mono10, NUM, type PillTone, type SynthesisPart } from "./ui";

const n0 = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-IN"));
const pctT = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : `${Number(v.toFixed(d))}%`);
const money = (v: number | null | undefined, signed = false) => fmtINR(v ?? null, { compact: v != null && Math.abs(v) >= 1_00_000, signed });
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

/** The synthesis: "{n} setups cleared the risk engine today — but {worst} already carry {x}% of open risk." (§2 01). */
export function synthesisOf(h: PaperHeadline | null): SynthesisPart[] {
  if (!h || h.setupsCleared == null) return ["Today's cleared setups could not be counted: the overview sent no headline."];
  const n = h.setupsCleared;
  const lead = `${n} ${plural(n, "setup", "setups")} cleared the risk engine today`;
  const w = h.worstConcentration;
  if (!w) return [`${lead}.`];
  return [`${lead} — but `, { hi: `${w.name} already carry ${pctT(w.pctOfOpenRisk, 1)} of open risk` }, "."];
}

/** "{signals} scanner signals consolidated into {opps} opportunities. {blocked} is blocked … and {reduced} is reduced …" */
export function proseOf(h: PaperHeadline | null): string | null {
  if (!h) return null;
  const parts: string[] = [];
  if (h.signals != null && h.opportunities != null) {
    parts.push(`${n0(h.signals)} scanner ${plural(h.signals, "signal", "signals")} consolidated into ${n0(h.opportunities)} ${plural(h.opportunities, "opportunity", "opportunities")}.`);
  }
  if (h.blocked != null && h.reduced != null) {
    const b = h.blocked === 0 ? "None is blocked by the risk engine" : `${n0(h.blocked)} ${plural(h.blocked, "is", "are")} blocked by the risk engine`;
    const r = h.reduced === 0 ? "none is reduced" : `${n0(h.reduced)} ${plural(h.reduced, "is", "are")} reduced to fit the risk budget`;
    parts.push(`${b} and ${r}.`);
  }
  return parts.length ? parts.join(" ") : null;
}

function Kpis({ k }: { k: PaperKpis }) {
  const orLevel = levelOf(k.openRiskPct, k.openRiskLimitPct);
  const ddTone: PillTone | undefined = k.drawdownPct != null && k.drawdownWarnPct != null && k.drawdownPct >= k.drawdownWarnPct ? "amber" : undefined;
  const dayTone: PillTone | undefined = k.dayPnlRs == null || k.dayPnlRs === 0 ? undefined : k.dayPnlRs > 0 ? "mint" : "danger";
  return (
    <KpiGrid min={170} testId="pv2-ov-kpis">
      <Kpi testId="pv2-kpi-equity" label="Account equity" value={money(k.equityRs)} sub={`start ${money(k.startEquityRs)}`} />
      <Kpi testId="pv2-kpi-day" label="Daily P&L" tone={dayTone} value={money(k.dayPnlRs, true)}
        sub={`limit ${k.dayLossLimitPct == null ? "—" : `−${pctT(Math.abs(k.dayLossLimitPct))}`} · used ${pctT(k.dayLossUsedPct, 1)}`} />
      <Kpi testId="pv2-kpi-deployed" label="Capital deployed" value={money(k.deployedRs)} sub={`${pctT(k.deployedPct, 1)} · cash ${money(k.cashRs)}`} />
      <Kpi testId="pv2-kpi-risk" label="Open planned risk" tone={orLevel === "amber" || orLevel === "danger" ? orLevel : undefined} value={pctT(k.openRiskPct)}
        sub={`of ${pctT(k.openRiskLimitPct)} budget`} />
      <Kpi testId="pv2-kpi-drawdown" label="Drawdown" tone={ddTone} value={pctT(k.drawdownPct)} sub={`warning at ${pctT(k.drawdownWarnPct)}`} />
      <Kpi testId="pv2-kpi-positions" label="Positions" value={`${n0(k.positionsOpen)} / ${n0(k.positionsMax)}`}
        sub={k.ordersPending == null ? "pending orders unknown" : `${n0(k.ordersPending)} pending ${plural(k.ordersPending, "order", "orders")}`} />
    </KpiGrid>
  );
}

const STAGE_LABEL: Record<string, string> = {
  signals: "Scanner signals", opportunities: "Opportunities", qualified: "Qualified", risk_approved: "Risk approved", orders_filled: "Orders filled", open_positions: "Open positions",
};
const STAGE_COLOUR: Record<string, string> = {
  signals: "var(--cp-ink-3)", opportunities: "var(--cp-indigo)", qualified: "var(--cp-indigo)", risk_approved: "var(--mint)", orders_filled: "var(--mint)", open_positions: "var(--mint)",
};

function Pipeline({ stages }: { stages: PipelineStage[] }) {
  const order = (s: string) => { const i = (PIPELINE_STAGES as readonly string[]).indexOf(s); return i < 0 ? 99 : i; };
  const rows = [...stages].sort((a, b) => order(a.stage) - order(b.stage));
  const base = rows.find((r) => r.stage === "signals")?.count ?? null;
  return (
    <Card title="Today's pipeline · signal → position" testId="pv2-pipeline">
      {!rows.length ? <Note testId="pv2-pipeline-empty">The overview sent no pipeline counts, so today's signal-to-position flow cannot be drawn.</Note> : (
        <ol className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 12 }}>
          {rows.map((r) => (
            <li key={r.stage} data-testid="pv2-pipeline-row" data-stage={r.stage} className="grid items-center"
              style={{ gridTemplateColumns: "minmax(0,130px) minmax(0,1fr) minmax(36px,auto)", gap: 12 }}>
              <span style={{ fontSize: 13, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{r.label ?? STAGE_LABEL[r.stage] ?? r.stage}</span>
              <ShareBar testId="pv2-pipeline-bar" colour={STAGE_COLOUR[r.stage] ?? "var(--cp-indigo)"} pct={base && r.count != null ? (r.count / base) * 100 : 0} />
              <span data-testid="pv2-pipeline-count" style={{ fontFamily: "var(--mono)", fontSize: 13, color: "var(--cp-ink)", textAlign: "right", ...NUM }}>{n0(r.count)}</span>
            </li>
          ))}
        </ol>
      )}
      {base === 0 && <Note testId="pv2-pipeline-none">No scanner signal is recorded today yet.</Note>}
      <Note>A scanner signal is not a trade. Each stage can reject, expire or reduce.</Note>
    </Card>
  );
}

const IST_HM = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
const hm = (iso: string | null) => { if (!iso) return null; const t = Date.parse(iso); return Number.isFinite(t) ? IST_HM.format(new Date(t)) : null; };
const RANK: Record<PaperWarning["level"], number> = { danger: 0, amber: 1, mint: 2 };

function Warnings({ items }: { items: PaperWarning[] }) {
  const rows = [...items].sort((a, b) => RANK[a.level] - RANK[b.level]);
  return (
    <Card title="Risk warnings" testId="pv2-warnings">
      {!rows.length ? <Note testId="pv2-warnings-none">No risk warning was raised today.</Note> : (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 12 }}>
          {rows.map((w, i) => {
            const meta = [w.code ? w.code.toUpperCase() : null, hm(w.at)].filter(Boolean).join(" · ");
            return (
              <li key={`${w.code ?? "w"}-${i}`} data-testid="pv2-warning" data-level={w.level} className="flex min-w-0" style={{ gap: 10 }}>
                <Dot tone={w.level} />
                <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
                  <span data-testid="pv2-warning-title" style={{ fontSize: 13.5, lineHeight: 1.45, color: w.level === "mint" ? "var(--mint)" : "var(--cp-ink)", overflowWrap: "anywhere" }}>
                    {w.title}{w.symbol ? ` · ${w.symbol}` : ""}
                  </span>
                  {meta && <span data-testid="pv2-warning-meta" style={{ ...mono10, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{meta}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function Body({ d, narrow }: { d: PaperOverview; narrow: boolean }) {
  return (
    <>
      <SectionHeader testId="pv2-ov-head" eyebrow="Trading overview" synthesis={synthesisOf(d.headline)} prose={proseOf(d.headline) ?? undefined} />
      {d.kpis ? <Kpis k={d.kpis} /> : <Note testId="pv2-ov-kpis-none">The overview sent no account figures, so equity, P&L, risk and positions are not shown.</Note>}
      <Split cols="minmax(0,1.3fr) minmax(0,1fr)" narrow={narrow} testId="pv2-ov-grid">
        <Pipeline stages={d.pipeline} />
        <Warnings items={d.warnings} />
      </Split>
    </>
  );
}

export function PaperOverview() {
  const q = usePaperOverview();
  const [narrow, ref] = useNarrow(900);
  return (
    <div ref={ref} data-testid="pv2-overview" className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      {q.isPending ? (
        <>
          <SectionHeader eyebrow="Trading overview" title="Reading today's paper desk…" />
          <LoadingBlock label="Reading the overview" rows={4} />
        </>
      ) : q.isError && !q.data ? (
        <>
          <SectionHeader eyebrow="Trading overview" title="Today's overview could not be read." />
          <div data-testid="pv2-ov-error"><QueryProblem what="The paper trading overview" error={q.error} onRetry={() => { void q.refetch(); }} /></div>
        </>
      ) : q.data ? <Body d={q.data} narrow={narrow} /> : null}
    </div>
  );
}
