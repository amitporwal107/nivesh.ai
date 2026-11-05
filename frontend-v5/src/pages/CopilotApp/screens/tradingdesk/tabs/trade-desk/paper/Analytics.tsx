/**
 * Paper Trading v2 › 06 Strategy analytics (?tab=trade&view=paper&sub=analytics) — the owner's design of 5 Nov 2026
 * (docs/scanner_paper_trading/UI_DESIGN_V2.md §2 "06 Strategy analytics"). Test cases PV2-A-50 … A-56.
 *
 *   header        eyebrow "Strategy analytics · last {days} days"; the synthesis "{best} earn the edge. {weakest} lack sample
 *                 size to scale." built from `by_setup` by a fixed rule (never an LLM)
 *   KPI tiles     Trades · Win rate · Expectancy · Profit factor · Max drawdown · Sharpe / Sortino (null with its reason)
 *   left          "Scanner attribution · signal outcome, not trade outcome": GET /api/v1/analytics/scanners (by scanner),
 *                 Signals · T+5 · T+20 · MFE / MAE · Evidence (Sufficient n ≥ 30 · Building · Low sample n < 15)
 *   right         "Certification · {setup}" (each criterion ✓ / ! / ×, "not measured" in amber) and "Expectancy by market
 *                 regime" (Uptrend / Sideways / Downtrend)
 *
 * Reads: GET /api/v1/analytics/account/{id}?days=90 (api-a.ts) and GET /api/v1/analytics/scanners?from= (spt-api.ts). Every
 * figure is the API's; a null one reads "—" with the reason the API gives. Read-only.
 */
import { useMemo, useState } from "react";
import { LoadingBlock } from "../../../../../components/ui";
import { QueryProblem } from "../../../../trading/parts";
import { useScannerAnalytics, type HorizonKey, type OutcomeRow } from "../spt-api";
import { useNarrow } from "../spt-parts";
import { daysAgoIst, useAccountAnalytics, type AccountAnalytics, type Certification, type RegimeRow, type SetupRow } from "./api-a";
import { Card, Eyebrow, Glyph, Kpi, KpiGrid, Note, Pill, SectionHeader, Split, NUM, mono10, type PillTone, type SynthesisPart } from "./ui";

const DAYS = 90;
const MIN_SAMPLE = 30;
const LOW_SAMPLE = 15;

const fx = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : v.toFixed(d));
const signed = (v: number | null | undefined, d = 2, unit = "") => (v == null || !Number.isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}${unit}`);
const pct1 = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(1)}%`);
const n0 = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-IN"));
const title = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const joinNames = (xs: string[]) => (xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** "{best} earn the edge. {weakest} lack sample size to scale." — best: the highest positive net expectancy with at least
 *  MIN_SAMPLE trades (else the highest positive one); weakest: every setup under MIN_SAMPLE trades. Fixed rules only. */
export function synthesisOf(a: AccountAnalytics | undefined): SynthesisPart[] {
  if (!a) return ["Strategy results for your paper account."];
  if (!a.trades) return [`No closed paper trade in the last ${a.days ?? DAYS} days, so there is no edge to measure yet.`];
  const rows = a.bySetup.filter((s) => s.setup !== "—");
  const positive = rows.filter((s) => (s.expectancyR ?? 0) > 0).sort((x, y) => (y.expectancyR as number) - (x.expectancyR as number));
  const best = positive.find((s) => (s.trades ?? 0) >= MIN_SAMPLE) ?? positive[0] ?? null;
  const weak = rows.filter((s) => s !== best && (s.trades ?? 0) < MIN_SAMPLE).map((s) => `${title(s.setup)} setups`);
  const parts: SynthesisPart[] = [];
  if (best) parts.push({ hi: `${title(best.setup)} setups`, tone: "mint" }, " earn the edge.");
  else parts.push(rows.length ? "No setup shows a positive net expectancy yet." : "The results were not broken down by setup.");
  if (weak.length) parts.push(" ", { hi: joinNames(weak) }, " lack sample size to scale.");
  return parts;
}

function Kpis({ a }: { a: AccountAnalytics }) {
  const ratios = a.sharpe == null && a.sortino == null ? "—" : `${fx(a.sharpe)} / ${fx(a.sortino)}`;
  return (
    <KpiGrid min={150} testId="pv2-an-kpis">
      <Kpi testId="pv2-an-trades" label="Trades" value={n0(a.trades)} sub="closed" />
      <Kpi testId="pv2-an-winrate" label="Win rate" value={pct1(a.winRatePct)} sub={`avg win ${signed(a.avgWinR, 2, "R")}`} />
      <Kpi testId="pv2-an-expectancy" label="Expectancy" tone={a.expectancyR == null || a.expectancyR === 0 ? undefined : a.expectancyR > 0 ? "mint" : "danger"}
        value={signed(a.expectancyR, 2, "R")} sub="net of costs" />
      <Kpi testId="pv2-an-pf" label="Profit factor" value={fx(a.profitFactor)} sub={a.profitFactor == null ? a.profitFactorReason ?? "not computed; no reason was sent" : "gross profit ÷ gross loss"} />
      <Kpi testId="pv2-an-dd" label="Max drawdown" value={a.maxDrawdownPct == null ? "—" : `${a.maxDrawdownPct.toFixed(2)}%`} sub="peak to trough" />
      <Kpi testId="pv2-an-ratios" label="Sharpe / Sortino" value={ratios} sub={a.sharpe == null || a.sortino == null ? a.ratioReason ?? "not computed; no reason was sent" : "from the daily P&L curve"} />
    </KpiGrid>
  );
}

// ── scanner attribution ──────────────────────────────────────────────────

const evidenceOf = (n: number | null): { label: string; tone: PillTone } =>
  n == null ? { label: "Unknown", tone: "plain" } : n >= MIN_SAMPLE ? { label: "Sufficient", tone: "mint" } : n < LOW_SAMPLE ? { label: "Low sample", tone: "danger" } : { label: "Building", tone: "amber" };
const hzCell = (r: OutcomeRow, h: HorizonKey) => {
  const x = r.horizons[h];
  return x ? signed(x.avgReturnPct, 2, "%") : "—";
};
const LONGEST: HorizonKey[] = ["t20", "t10", "t5", "t1"];
const mfeMae = (r: OutcomeRow) => {
  const h = LONGEST.find((k) => r.horizons[k]?.avgMfePct != null || r.horizons[k]?.avgMaePct != null);
  const x = h ? r.horizons[h] : null;
  return x ? `${signed(x.avgMfePct, 1, "%")} / ${signed(x.avgMaePct, 1, "%")}` : "—";
};
const ACOLS = "minmax(140px,1.6fr) minmax(60px,0.7fr) minmax(70px,0.8fr) minmax(70px,0.8fr) minmax(110px,1.1fr) minmax(100px,1fr)";

function Attribution() {
  const from = useMemo(() => daysAgoIst(DAYS), []);
  const q = useScannerAnalytics({ from, to: "", kind: "" });
  const rows = q.data?.byScanner ?? [];
  return (
    <Card title="Scanner attribution · signal outcome, not trade outcome" testId="pv2-an-attr">
      {q.isPending ? <LoadingBlock label="Reading scanner outcomes" rows={3} />
        : q.isError ? <div data-testid="pv2-an-attr-error"><QueryProblem what="Scanner outcomes" error={q.error} onRetry={() => { void q.refetch(); }} /></div>
        : !rows.length ? <Note testId="pv2-an-attr-empty">No scanner signal outcome is recorded from {q.data?.from ?? from} to {q.data?.to ?? "today"}.</Note>
        : (
          <div className="cp-scroll min-w-0" style={{ overflowX: "auto" }}>
            <div role="table" aria-label="Scanner attribution" style={{ minWidth: 600 }}>
              <div role="row" className="grid" style={{ gridTemplateColumns: ACOLS, gap: 10, paddingBottom: 8, borderBottom: "1px solid var(--cp-line)" }}>
                {["Scanner", "Signals", "T+5", "T+20", "MFE / MAE", "Evidence"].map((h) => <span key={h} role="columnheader" style={{ ...mono10, color: "var(--cp-ink-3)" }}>{h}</span>)}
              </div>
              {rows.map((r) => {
                const ev = evidenceOf(r.signals);
                return (
                  <div key={r.key} role="row" data-testid="pv2-an-attr-row" data-key={r.key} className="grid items-center"
                    style={{ gridTemplateColumns: ACOLS, gap: 10, padding: "10px 0", borderBottom: "1px solid var(--cp-line)", fontSize: 13 }}>
                    <span role="cell" style={{ color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{r.key}</span>
                    <span role="cell" data-testid="pv2-an-attr-n" style={{ fontFamily: "var(--mono)", ...NUM }}>{n0(r.signals)}</span>
                    <span role="cell" data-testid="pv2-an-attr-t5" style={{ fontFamily: "var(--mono)", ...NUM }}>{hzCell(r, "t5")}</span>
                    <span role="cell" data-testid="pv2-an-attr-t20" style={{ fontFamily: "var(--mono)", ...NUM }}>{hzCell(r, "t20")}</span>
                    <span role="cell" data-testid="pv2-an-attr-mfe" style={{ fontFamily: "var(--mono)", ...NUM }}>{mfeMae(r)}</span>
                    <span role="cell"><Pill tone={ev.tone} testId="pv2-an-attr-evidence">{ev.label}</Pill></span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      <Note>T+5 and T+20 are the signals' average returns after 5 and 20 sessions, in the signal's direction; MFE / MAE the average best and worst move. Evidence: Sufficient from {MIN_SAMPLE} signals, Low sample under {LOW_SAMPLE}. {q.data?.note ?? ""}</Note>
    </Card>
  );
}

// ── certification ────────────────────────────────────────────────────────

function CertificationCard({ certs }: { certs: Certification[] }) {
  const [pick, setPick] = useState(0);
  const c = certs[Math.min(pick, certs.length - 1)] ?? null;
  return (
    <Card title={`Certification · ${c ? title(c.setup) : "no setup"}`} testId="pv2-an-cert"
      right={c?.certified != null ? <Pill tone={c.certified ? "mint" : "amber"} testId="pv2-an-cert-state">{c.certified ? "Certified" : "Not certified"}</Pill> : undefined}>
      {certs.length > 1 && (
        <div role="group" aria-label="Setup" className="flex flex-wrap" style={{ gap: 6 }}>
          {certs.map((x, i) => (
            <button key={x.setup} type="button" data-testid="pv2-an-cert-pick" aria-pressed={i === pick} onClick={() => setPick(i)}
              style={{ padding: "3px 10px", borderRadius: 999, border: `1px solid ${i === pick ? "var(--mint-line)" : "var(--line-2)"}`, background: i === pick ? "var(--mint-soft)" : "transparent",
                color: i === pick ? "var(--mint)" : "var(--cp-ink-2)", ...mono10, cursor: "pointer" }}>{title(x.setup)}</button>
          ))}
        </div>
      )}
      {!c ? <Note testId="pv2-an-cert-none">No setup has a certification record yet: it starts with the first closed trade.</Note> : (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 8 }}>
          {c.criteria.map((k) => (
            <li key={k.key} data-testid="pv2-an-criterion" data-status={k.status} className="flex min-w-0 items-start" style={{ gap: 9 }}>
              <Glyph kind={k.status === "not_measured" ? "not_measured" : k.status} />
              <span className="flex min-w-0 flex-1 flex-wrap justify-between" style={{ gap: "2px 10px", fontSize: 13 }}>
                <span style={{ color: "var(--cp-ink)" }}>{k.label}</span>
                <span data-testid="pv2-an-criterion-value" style={{ fontFamily: "var(--mono)", fontSize: 12, color: k.status === "not_measured" ? "var(--amber)" : "var(--cp-ink-2)", ...NUM }}>
                  {k.status === "not_measured" ? `not measured${k.value ? ` · ${k.value}` : ""}` : k.value ?? "—"}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <Note>Risk allocation increases only after every criterion passes. A winning streak alone does not qualify.</Note>
    </Card>
  );
}

const REGIME_ORDER = ["uptrend", "sideways", "downtrend", "unknown"];

function Regimes({ rows }: { rows: RegimeRow[] }) {
  const sorted = [...rows].sort((a, b) => REGIME_ORDER.indexOf(a.regime) - REGIME_ORDER.indexOf(b.regime));
  const max = Math.max(0, ...sorted.map((r) => Math.abs(r.expectancyR ?? 0)));
  return (
    <Card title="Expectancy by market regime" testId="pv2-an-regime">
      {!sorted.length ? <Note testId="pv2-an-regime-none">No closed trade carries a market regime at entry yet.</Note> : (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 10 }}>
          {sorted.map((r) => {
            const v = r.expectancyR;
            const colour = v == null || v === 0 ? "var(--cp-ink-3)" : v > 0 ? "var(--mint)" : "var(--cp-danger)";
            return (
              <li key={r.regime} data-testid="pv2-an-regime-row" data-regime={r.regime} className="grid items-center" style={{ gridTemplateColumns: "minmax(0,96px) minmax(0,1fr) minmax(64px,auto)", gap: 10 }}>
                <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{title(r.regime)}<span style={{ ...mono10, marginLeft: 6, color: "var(--cp-ink-3)" }}>{n0(r.trades)}</span></span>
                <div style={{ height: 6, borderRadius: 999, background: "var(--bg-3)", overflow: "hidden" }}>
                  <div style={{ width: `${max && v != null ? (Math.abs(v) / max) * 100 : 0}%`, height: "100%", borderRadius: 999, background: colour }} />
                </div>
                <span data-testid="pv2-an-regime-value" style={{ fontFamily: "var(--mono)", fontSize: 13, color: colour, textAlign: "right", ...NUM }}>{signed(v, 2, "R")}</span>
              </li>
            );
          })}
        </ul>
      )}
      <Note>The regime is the validation's market regime when the trade opened.</Note>
    </Card>
  );
}

// ── the screen ───────────────────────────────────────────────────────────

export function PaperAnalytics({ accountId }: { accountId: string | null }) {
  const q = useAccountAnalytics(accountId, DAYS);
  const [narrow, ref] = useNarrow(900);
  const a = q.data;
  return (
    <div ref={ref} data-testid="pv2-analytics" className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      <SectionHeader testId="pv2-an-head" eyebrow={`Strategy analytics · last ${a?.days ?? DAYS} days`}
        synthesis={a ? synthesisOf(a) : undefined} title={a ? undefined : q.isError ? "Your strategy results could not be read." : accountId ? "Reading your strategy results…" : "Waiting for your paper account…"} />
      {q.isError ? <div data-testid="pv2-an-error"><QueryProblem what="Your strategy analytics" error={q.error} onRetry={() => { void q.refetch(); }} /></div>
        : !a ? <LoadingBlock label="Reading your strategy analytics" rows={3} />
        : <Kpis a={a} />}
      <Split cols="minmax(0,1.5fr) minmax(0,1fr)" narrow={narrow} testId="pv2-an-grid">
        <Attribution />
        <div className="flex min-w-0 flex-col" style={{ gap: 16 }}>
          {a ? <CertificationCard certs={a.certification} /> : null}
          {a ? <Regimes rows={a.byRegime} /> : null}
        </div>
      </Split>
      {a && (a.basis || a.notes.length > 0) && (
        <Note testId="pv2-an-notes">{[a.basis, ...a.notes].filter(Boolean).join(" ")}</Note>
      )}
    </div>
  );
}

export type { SetupRow };
