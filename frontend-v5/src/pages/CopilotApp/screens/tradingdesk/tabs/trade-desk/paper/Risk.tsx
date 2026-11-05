/**
 * Paper Trading v2 › 04 Portfolio risk (?tab=trade&view=paper&sub=risk) — the owner's design of 5 Nov 2026,
 * docs/scanner_paper_trading/UI_DESIGN_V2.md §2.04 and §3.
 *
 *   header      synthesis "Within every limit, with {nearest} the nearest to a breach." / "{n} limits breached: {names}." —
 *               a fixed template over the limit rows below (never a model)
 *   policy      "Configure · risk limits" (the shared draft, policy.tsx): halt must sit above restricted
 *   left        "Limit utilization": each row "value / limit" against the DRAFT limits, NEAR LIMIT (> 80 %) / BREACH (> 100 %)
 *                                                       GET /api/v1/risk/account/{id} · /risk/exposures/{id} · /paper/fno-structures
 *   right       "Correlation · 60d returns" (GET /api/v1/risk/correlation/{id}; ≥ 0.70 danger, null cells "—") and
 *               "Stress scenarios · portfolio ₹ loss" (GET /api/v1/risk/stress-test/{id}, every scenario with its assumption)
 *   F&O         "F&O · N strategies · net Greeks": Greek tiles, max loss by strategy vs the per-strategy limit, scenario P&L
 *   caps        "F&O structure caps (additional checks)": the existing risk-controls feature (GET /api/risk/policy, the gate from
 *               GET /api/risk/status; services/risk_controls) in the design's layout, collapsible. The caps and the gate have no
 *               write route, so the Allowed column and the gate pill show the state and say who changes it.
 *
 * Paper only; nothing reaches a broker. Every empty or failed read says what is missing.
 */
import { useState, type ReactNode } from "react";
import { LoadingBlock, fmtNum } from "../../../../../components/ui";
import { QueryProblem } from "../../../../trading/parts";
import { useRiskPolicy, useRiskStatus } from "../../../risk-controls";
import { useSptExposures, useSptRiskAccount, type SptExposures, type SptRiskAccount } from "../../risk-desk/spt-risk-api";
import { MONO } from "../pnl-ui";
import { useNarrow } from "../spt-parts";
import { useCorrelation, useFnoStructures, useStress, type FnoBook } from "./api-b";
import { AccountMissing, CorrMatrix, DASH, LimitFlag, LimitRow, ValueBar, ofPct, pctTxt, rs0, rsS, signTone } from "./b-parts";
import { PolicyCard, usePolicyDraft, type PolicyDraft } from "./policy";
import { Card, Eyebrow, Note, Pill, SectionHeader, Split, Tile, levelOf, mono10, toneColor, type SynthesisPart } from "./ui";

// ── the limit rows (from the DRAFT limits: the bars move before a save) ──

export interface LimitFig { k: string; name: string; used: number | null; limit: number | null; show: (v: number | null) => string; note: string | null }

/** How a row is named inside the header sentence ("…, with daily loss the nearest to a breach."). */
function phraseOf(r: LimitFig): string {
  const [head, tail] = r.name.split(" · ");
  if (r.k === "single_stock" && tail) return `${tail}'s weight`;
  if (r.k === "fno_max_loss" && tail) return `${tail}'s max loss`;
  return head.charAt(0).toLowerCase() + head.slice(1);
}

const pctShow = (v: number | null) => pctTxt(v, 2);
const countShow = (v: number | null) => (v == null ? DASH : fmtNum(v));

export function limitRows(a: SptRiskAccount | undefined, ex: SptExposures | undefined, fno: FnoBook | undefined, fnoLoaded: boolean, d: PolicyDraft): LimitFig[] {
  const eq = a?.equityRs ?? null;
  const cap = eq != null && d.eff("max_open_risk_pct") != null ? (eq * (d.eff("max_open_risk_pct") as number)) / 100 : null;
  const top = ex?.byInstrument.reduce<{ key: string; pct: number } | null>((b, r) => (r.pctOfEquity != null && (!b || r.pctOfEquity > b.pct) ? { key: r.key, pct: r.pctOfEquity } : b), null) ?? null;
  const structures = fno?.structures ?? [];
  const biggest = structures.reduce<{ name: string; rs: number } | null>((b, s) => (s.maxLossRs != null && (!b || s.maxLossRs > b.rs) ? { name: s.name, rs: s.maxLossRs } : b), null);
  const margin = fnoLoaded ? (structures.length ? fno?.totals.marginRs ?? null : 0) : null;
  return [
    { k: "open_risk", name: "Open planned risk", used: a?.openRisk.rs ?? null, limit: cap, show: rs0, note: a?.openRisk.rs == null ? "Open risk unknown: the account route sent no figure." : null },
    { k: "stressed", name: "Stressed portfolio loss", used: a?.sptRisk?.stressedRs ?? null, limit: cap, show: rs0,
      note: a?.sptRisk ? `Every stop gapping by ${pctTxt(a.sptRisk.stressedGapPct, 1)}, against the open-risk limit.` : "Not sent: the account could not be read." },
    { k: "daily_loss", name: "Daily loss", used: a?.dailyLoss.lossPct ?? null, limit: d.eff("daily_loss_pct"), show: pctShow, note: null },
    { k: "weekly_loss", name: "Weekly loss", used: a?.weeklyLoss.lossPct ?? null, limit: d.eff("weekly_loss_pct"), show: pctShow, note: null },
    { k: "drawdown", name: "Drawdown", used: a?.drawdown.pct ?? null, limit: d.eff("halt_at_pct"), show: pctShow,
      note: d.eff("restrict_at_pct") != null ? `New positions are restricted from ${pctTxt(d.eff("restrict_at_pct"), 1)}; trading halts at the limit.` : null },
    { k: "single_stock", name: top ? `Max single stock · ${top.key}` : "Max single stock", used: ex ? top?.pct ?? 0 : null, limit: d.eff("max_position_pct"), show: pctShow,
      note: ex ? (top ? null : "No open position.") : "Exposure by instrument could not be read." },
    { k: "margin", name: "Margin utilization", used: ofPct(margin, eq) ?? (margin === 0 ? 0 : null), limit: d.eff("margin_util_pct"), show: pctShow,
      note: !fnoLoaded ? "The F&O structures could not be read, so margin is unknown." : structures.length ? "F&O margin of the open paper structures, % of equity." : "No open paper F&O structure, so no margin is used." },
    { k: "positions", name: "Open positions", used: a?.utilisation.positionsOpen ?? null, limit: d.eff("max_positions"), show: countShow, note: null },
    { k: "fno_max_loss", name: biggest ? `Largest F&O strategy max loss · ${biggest.name}` : "Largest F&O strategy max loss",
      used: biggest ? ofPct(biggest.rs, eq) : fnoLoaded ? 0 : null, limit: d.eff("fno_max_loss_pct"), show: pctShow,
      note: !fnoLoaded ? "The F&O structures could not be read." : biggest ? null : "No open paper F&O structure." },
  ];
}

export function riskSynthesis(rows: LimitFig[], accountRead: boolean): SynthesisPart[] {
  const known = rows.filter((r) => levelOf(r.used, r.limit) != null);
  if (!accountRead || !known.length) return ["Limit use is unknown: the account could not be read."];
  const breached = known.filter((r) => levelOf(r.used, r.limit) === "danger");
  if (breached.length) {
    return [{ hi: `${breached.length} limit${breached.length === 1 ? "" : "s"} breached: `, tone: "danger" }, `${breached.map((r) => r.name).join(", ")}.`];
  }
  const nearest = known.reduce((b, r) => ((r.used as number) / (r.limit as number) > (b.used as number) / (b.limit as number) ? r : b));
  return ["Within every limit, with ", { hi: phraseOf(nearest) }, " the nearest to a breach."];
}

// ── correlation, stress ──────────────────────────────────────────────────

function CorrelationCard({ accountId }: { accountId: string }) {
  const q = useCorrelation(accountId);
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading the correlations" rows={2} />;
  else if (q.isError) body = <div data-testid="pv2-rk-corr-error"><QueryProblem what="The correlation matrix" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  else if (q.data.symbols.length < 2) body = <Note testId="pv2-rk-corr-empty">Fewer than two open positions, so there is nothing to correlate.</Note>;
  else {
    body = (
      <>
        <CorrMatrix c={q.data} />
        {q.data.symbols.length > 6 && <Note>Showing the first 6 of {q.data.symbols.length} positions.</Note>}
        {q.data.notes.length > 0 && <ul data-testid="pv2-rk-corr-notes" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16, fontSize: 11.5, color: "var(--cp-ink-3)" }}>{q.data.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        {q.data.basis && <Note>{q.data.basis}</Note>}
      </>
    );
  }
  return (
    <Card testId="pv2-rk-corr" title={`Correlation · ${q.data?.days ?? 60}d returns`} right={<Eyebrow>≥{(q.data?.threshold ?? 0.7).toFixed(2)} = concentrated</Eyebrow>}>
      {body}
    </Card>
  );
}

function StressCard({ accountId }: { accountId: string }) {
  const q = useStress(accountId);
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Running the stress scenarios" rows={3} />;
  else if (q.isError) body = <div data-testid="pv2-rk-stress-error"><QueryProblem what="The stress test" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  else if (!q.data.rows.length) body = <Note testId="pv2-rk-stress-empty">The stress test sent no scenarios.</Note>;
  else {
    const max = Math.max(0, ...q.data.rows.map((r) => (r.lossRs == null ? 0 : Math.abs(r.lossRs))));
    body = (
      <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
        {q.data.rows.map((r) => (
          <div key={r.key} data-testid="pv2-rk-stress-row" data-key={r.key} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
            <div className="flex min-w-0 justify-between" style={{ gap: 10, fontSize: 12.5 }}>
              <span style={{ color: "var(--cp-ink)" }}>{r.label}</span>
              <span data-testid="pv2-rk-stress-loss" style={{ fontFamily: MONO, color: r.lossRs ? toneColor("danger") : "var(--cp-ink-2)", fontVariantNumeric: "tabular-nums" }}>{rs0(r.lossRs)}</span>
            </div>
            <div style={{ height: 6, borderRadius: 999, background: "var(--bg-3)", overflow: "hidden" }}>
              <div style={{ width: `${r.lossRs == null || !max ? 0 : (Math.abs(r.lossRs) / max) * 100}%`, height: "100%", background: toneColor("danger"), borderRadius: 999 }} />
            </div>
            {r.assumption && <Note>{r.assumption}</Note>}
          </div>
        ))}
        {q.data.base.unpriced.length > 0 && (
          <Note style={{ color: "var(--amber)" }}>{q.data.base.unpriced.length} {q.data.base.unpriced.length === 1 ? "entry is" : "entries are"} not priced yet and left out of every scenario.</Note>
        )}
      </div>
    );
  }
  return <Card testId="pv2-rk-stress" title="Stress scenarios · portfolio ₹ loss">{body}<Note>Scenarios are assumptions, not forecasts.</Note></Card>;
}

// ── F&O net Greeks ───────────────────────────────────────────────────────

function FnoGreeksCard({ q, eq, d }: { q: ReturnType<typeof useFnoStructures>; eq: number | null; d: PolicyDraft }) {
  const n = q.data?.structures.length ?? 0;
  const lim = d.eff("fno_max_loss_pct");
  const perStrategy = eq != null && lim != null ? (eq * lim) / 100 : null;
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading your F&O structures" rows={2} />;
  else if (q.isError) body = <div data-testid="pv2-rk-fno-error"><QueryProblem what="Your paper F&O structures" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  else if (!n) body = <Note testId="pv2-rk-fno-empty">No open paper F&O structure on the desk, so there are no Greeks to net.</Note>;
  else {
    const b = q.data;
    const t = b.totals.net;
    // Scenario P&L across every structure: summed only when every structure has the scenario (a partial sum is not shown).
    const names: Array<{ name: string; label: string }> = [];
    for (const s of b.structures) for (const c of s.scenarios) if (!names.some((x) => x.name === c.name)) names.push({ name: c.name, label: c.label });
    const scen = names.map((x) => {
      const vals = b.structures.map((s) => s.scenarios.find((c) => c.name === x.name)?.pnlRs ?? null);
      const missing = vals.filter((v) => v == null).length;
      return { ...x, pnl: missing ? null : (vals as number[]).reduce((a, v) => a + v, 0), missing };
    });
    const tile = (label: string, value: ReactNode, id: string, sub?: ReactNode) => (
      <Tile testId={id}>
        <Eyebrow>{label}</Eyebrow>
        <span style={{ fontFamily: MONO, fontSize: 15, color: "var(--cp-ink)", fontVariantNumeric: "tabular-nums" }}>{value}</span>
        {sub && <span style={{ fontSize: 11, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{sub}</span>}
      </Tile>
    );
    body = (
      <div className="flex min-w-0 flex-col" style={{ gap: 14 }}>
        <div className="grid min-w-0" style={{ gap: 8, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,130px),1fr))" }}>
          {tile("Net delta", t.delta == null ? DASH : fmtNum(t.delta, 2), "pv2-rk-greek-delta",
            b.structures.map((s) => `${s.underlying ?? s.name} ${s.net.delta == null ? DASH : fmtNum(s.net.delta, 2)}`).join(" · "))}
          {tile("Net gamma", t.gamma == null ? DASH : fmtNum(t.gamma, 4), "pv2-rk-greek-gamma")}
          {tile("Net theta", t.thetaRsDay == null ? DASH : `${rsS(t.thetaRsDay)} / day`, "pv2-rk-greek-theta")}
          {tile("Net vega", t.vegaRsPt == null ? DASH : `${rsS(t.vegaRsPt)} / IV pt`, "pv2-rk-greek-vega")}
          {tile("Margin", rs0(b.totals.marginRs), "pv2-rk-greek-margin")}
        </div>
        <div className="grid min-w-0" style={{ gap: 16, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", alignItems: "start" }}>
          <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
            <Eyebrow>Max loss by strategy · vs per-strategy limit</Eyebrow>
            {b.structures.map((s) => {
              const partial = s.status === "partial" || s.legs.some((l) => l.pending);
              return (
                <div key={s.id} data-testid="pv2-rk-fno-row" data-id={s.id} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
                  <div className="flex min-w-0 flex-wrap justify-between" style={{ gap: "2px 10px", fontSize: 12.5 }}>
                    <span className="flex items-baseline" style={{ gap: 8 }}>
                      <span style={{ color: "var(--cp-ink)" }}>{s.name}</span>
                      <LimitFlag level={levelOf(s.maxLossRs, perStrategy)} testId="pv2-rk-fno-flag" />
                    </span>
                    <span style={{ fontFamily: MONO, color: "var(--cp-ink-2)" }}>{rs0(s.maxLossRs)} / {rs0(perStrategy)}</span>
                  </div>
                  <ValueBar used={s.maxLossRs} limit={perStrategy} label={`${s.name} max loss of the per-strategy limit`} testId="pv2-rk-fno-bar" height={6} />
                  {partial && <span data-testid="pv2-rk-fno-unhedged" style={{ fontSize: 11.5, color: toneColor("amber") }}>Unhedged · hedge leg pending</span>}
                </div>
              );
            })}
          </div>
          <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
            <Eyebrow>F&amp;O scenario P&amp;L · all strategies</Eyebrow>
            {scen.length ? scen.map((x) => (
              <div key={x.name} data-testid="pv2-rk-fno-scenario" data-name={x.name} className="flex min-w-0 justify-between" style={{ gap: 10, fontSize: 12.5, padding: "4px 0", borderBottom: "1px solid var(--cp-line)" }}>
                <span style={{ color: "var(--cp-ink-2)" }}>{x.label}</span>
                <span data-testid="pv2-rk-fno-scenario-pnl" style={{ fontFamily: MONO, color: toneColor(signTone(x.pnl)), fontVariantNumeric: "tabular-nums" }}
                  title={x.missing ? `Not computed for ${x.missing} structure${x.missing === 1 ? "" : "s"}` : undefined}>{rsS(x.pnl)}</span>
              </div>
            )) : <Note>The structures carry no scenario figures.</Note>}
            <Note>Scenarios are assumptions, not forecasts.</Note>
          </div>
        </div>
        {b.basis && <Note>{b.basis}</Note>}
      </div>
    );
  }
  return (
    <Card testId="pv2-rk-fno" title={`F&O · ${n} ${n === 1 ? "strategy" : "strategies"} · net Greeks`}
      right={q.data && n > 0 ? <Pill tone="indigo" testId="pv2-rk-fno-sum">Sum of max loss · {rs0(q.data.totals.maxLossRs)}</Pill> : undefined}>
      {body}
    </Card>
  );
}

// ── F&O structure caps (the existing risk-controls feature) ──────────────

const capCell = { padding: "8px 8px", borderBottom: "1px solid var(--cp-line)", fontSize: 13, verticalAlign: "middle" } as const;

function CapsCard() {
  const [open, setOpen] = useState(true);
  const status = useRiskStatus();
  const policy = useRiskPolicy();
  const gate = status.data?.gateEnabled ?? null;
  const p = policy.data;
  const u = p?.usage ?? null;
  const rows: Array<{ key: string; label: string; allowed: number | null; used: number | null; rupees?: boolean; yesNo?: boolean | null }> = p ? [
    { key: "legs", label: "Legs per structure", allowed: p.maxLegs, used: null },
    { key: "lots", label: "Lots per leg", allowed: p.maxLotsPerLeg, used: null },
    { key: "structures", label: "Open structures", allowed: p.maxOpenStructures, used: u ? u.openStructures : null },
    { key: "capital", label: "Capital at risk", allowed: p.maxCapitalAtRiskRs, used: u ? u.capitalAtRiskRs : null, rupees: true },
    { key: "defined", label: "Defined risk only", allowed: null, used: null, yesNo: p.requireDefinedRisk },
  ] : [];
  const fmt = (v: number | null, rupees?: boolean) => (v == null ? DASH : rupees ? rs0(v) : fmtNum(v));
  const remaining = (r: (typeof rows)[number]): ReactNode => {
    if (gate !== true || r.allowed == null || r.used == null) return DASH;
    const left = r.allowed - r.used;
    return left < 0 ? <span style={{ color: toneColor("danger") }}>Over by {fmt(-left, r.rupees)}</span> : fmt(left, r.rupees);
  };
  const gatePill = gate === true ? <Pill tone="mint" testId="pv2-rk-gate" attrs={{ "data-gate": "on" }}>Gate on for your account</Pill>
    : gate === false ? <Pill tone="amber" testId="pv2-rk-gate" attrs={{ "data-gate": "off" }}>Gate off for your account</Pill>
      : <Pill tone="plain" testId="pv2-rk-gate" attrs={{ "data-gate": "unknown" }}>Gate state unknown</Pill>;
  const boxStyle = { width: 110, padding: "5px 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontFamily: MONO, fontSize: 12.5, textAlign: "right" as const };
  return (
    <section data-testid="pv2-rk-caps" data-open={open ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 12, padding: 18, borderRadius: 14, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <div className="flex min-w-0 flex-wrap items-center justify-between" style={{ gap: "6px 12px" }}>
        <button type="button" data-testid="pv2-rk-caps-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}
          className="flex items-center" style={{ gap: 8, padding: 0, border: 0, background: "none", cursor: "pointer", color: "var(--cp-ink-3)" }}>
          <span aria-hidden style={{ display: "inline-block", transform: open ? "rotate(90deg)" : "none", transition: "transform 150ms ease", fontSize: 11 }}>▶</span>
          <Eyebrow as="h3">F&amp;O structure caps (additional checks)</Eyebrow>
        </button>
        {status.isSuccess ? gatePill : status.isError ? <Pill tone="plain" testId="pv2-rk-gate" attrs={{ "data-gate": "unknown" }}>Gate state unknown</Pill> : null}
      </div>
      {open && (
        <>
          {gate === false && <Note testId="pv2-rk-gate-note">The policy gate does not check your paper writes, so these limits are not applied to them. The kill switch and the halt still apply.</Note>}
          {gate === true && <Note testId="pv2-rk-gate-note">The policy gate checks your paper writes against these limits before an order is created. The kill switch and the halt also apply.</Note>}
          {status.isError && <Note testId="pv2-rk-gate-note">The gate's state could not be read, so Remaining is not shown.</Note>}
          {policy.isPending && <LoadingBlock label="Loading the structure caps" rows={2} />}
          {policy.isError && <div data-testid="pv2-rk-caps-error"><QueryProblem what="The structure caps" error={policy.error} onRetry={() => { void policy.refetch(); }} /></div>}
          {p && (
            <div className="min-w-0" style={{ overflowX: "auto" }}>
              <table data-testid="pv2-rk-caps-table" style={{ width: "100%", minWidth: 340, borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["Limit", "Allowed", "Used", "Remaining"].map((h, i) => (
                      <th key={h} scope="col" style={{ ...capCell, ...mono10, color: "var(--cp-ink-3)", fontWeight: 400, textAlign: i ? "right" : "left" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.key} data-testid={`pv2-rk-cap-${r.key}`}>
                      <th scope="row" style={{ ...capCell, textAlign: "left", fontWeight: 400, color: "var(--cp-ink)" }}>{r.label}</th>
                      <td style={{ ...capCell, textAlign: "right" }}>
                        {r.yesNo !== undefined ? (
                          <span data-testid={`pv2-rk-cap-${r.key}-allowed`} role="group" aria-label="Defined risk only" className="inline-flex" style={{ gap: 2, padding: 2, borderRadius: 999, background: "var(--bg-2)" }}>
                            {(["Yes", "No"] as const).map((w) => {
                              const on = r.yesNo == null ? false : (w === "Yes") === r.yesNo;
                              return <span key={w} data-on={on ? "true" : "false"} style={{ padding: "3px 10px", borderRadius: 999, ...mono10, background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>{w}</span>;
                            })}
                          </span>
                        ) : (
                          <span className="inline-flex items-center" style={{ gap: 4 }}>
                            {r.rupees && <span style={{ ...mono10, color: "var(--cp-ink-3)" }}>₹</span>}
                            <input data-testid={`pv2-rk-cap-${r.key}-allowed`} readOnly aria-readonly="true" aria-label={`${r.label} allowed`}
                              value={r.allowed == null ? DASH : r.rupees ? r.allowed.toLocaleString("en-IN") : String(r.allowed)} style={boxStyle} />
                          </span>
                        )}
                      </td>
                      <td data-testid={`pv2-rk-cap-${r.key}-used`} style={{ ...capCell, textAlign: "right", fontFamily: MONO }}>{fmt(r.used, r.rupees)}</td>
                      <td data-testid={`pv2-rk-cap-${r.key}-left`} style={{ ...capCell, textAlign: "right", fontFamily: MONO }}>{remaining(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {p && !u && <Note>The route sent no usage figures, so used and remaining are not shown.</Note>}
          <Note testId="pv2-rk-caps-readonly">The allowed values are this policy's fixed limits: no route changes them in this release, so they are shown, not edited. An admin switches the gate for an account.</Note>
          <span data-testid="pv2-rk-caps-footer" style={{ ...mono10, color: "var(--cp-ink-3)", borderTop: "1px solid var(--cp-line)", paddingTop: 10 }}>
            Risk controls · Rules-based · {(p?.policyVersion ?? "fno-risk-v1").toUpperCase()}
          </span>
        </>
      )}
    </section>
  );
}

// ── the view ─────────────────────────────────────────────────────────────

export function PaperRisk({ accountId }: { accountId: string | null }) {
  const [narrow, ref] = useNarrow(900);
  const d = usePolicyDraft(accountId);
  const acc = useSptRiskAccount(accountId);
  const ex = useSptExposures(accountId);
  const fno = useFnoStructures(!!accountId);
  const a = acc.data;
  const eq = a?.equityRs ?? null;
  const rows = limitRows(a, ex.data, fno.data, fno.isSuccess, d);
  const maxOpen = d.eff("max_open_risk_pct");
  const usedPct = a?.openRisk.usedPctOfEquity ?? ofPct(a?.openRisk.rs, eq);
  const leftPct = maxOpen != null && usedPct != null ? maxOpen - usedPct : null;
  const sub = <>Risk budget left {pctTxt(leftPct, 2)} ({rs0(eq != null && leftPct != null ? (eq * leftPct) / 100 : null)}). The risk engine enforces these as hard limits.</>;

  if (!accountId) {
    return (
      <div data-testid="pv2-risk" className="flex min-w-0 flex-col" style={{ gap: 18 }}>
        <SectionHeader testId="pv2-rk-head" eyebrow="Portfolio risk" synthesis={["Limit use is unknown."]} />
        <AccountMissing what="there is no portfolio risk to show" />
      </div>
    );
  }
  return (
    <div ref={ref} data-testid="pv2-risk" className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      <SectionHeader testId="pv2-rk-head" eyebrow="Portfolio risk" synthesis={riskSynthesis(rows, !!a)} />
      {acc.isError && <div data-testid="pv2-rk-error"><QueryProblem what="Your account's risk" error={acc.error} onRetry={() => { void acc.refetch(); }} /></div>}
      <PolicyCard panel="risk" d={d} sub={sub} narrow={narrow} />
      <Split cols="minmax(0,1fr) minmax(0,1fr)" narrow={narrow} testId="pv2-rk-grid">
        <Card testId="pv2-rk-limits" title="Limit utilization">
          {acc.isPending ? <LoadingBlock label="Reading your account's risk" rows={4} /> : (
            <div className="flex min-w-0 flex-col">
              {rows.map((r) => <LimitRow key={r.k} k={r.k} name={r.name} used={r.used} limit={r.limit} show={r.show} note={r.note} />)}
            </div>
          )}
          <Note>Limits are the draft's: the bars move as you edit the policy, before it is saved. Amber over 80% of a limit; red over 100%.</Note>
        </Card>
        <div className="flex min-w-0 flex-col" style={{ gap: 16 }}>
          <CorrelationCard accountId={accountId} />
          <StressCard accountId={accountId} />
        </div>
      </Split>
      <FnoGreeksCard q={fno} eq={eq} d={d} />
      <CapsCard />
      <Note>Paper only: nothing here is sent to a broker. Real holdings are not counted.</Note>
    </div>
  );
}
