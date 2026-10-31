/**
 * Smart trading desk — 02 AI Opportunity scanner, "Reversal candidates" (PRD §5.2, §5.7, §5.8).
 *
 *   GET /api/positional/reversal-candidates?near_pct=&view=&limit=   (useReversalCandidates, reversal-data.ts)
 *
 * Stocks near their 252-session low that show stabilization evidence. Near the low is a screen, not a signal: the list
 * holds only stocks with enough independent evidence, and every row says what is confirmed, what is not and what is
 * unknown. The score is rule-based (hypothesis weights, not tuned) and is not a probability; a component that could not
 * be measured says "Unknown" and is left out of the total, never counted as neutral. Entry trigger, invalidation and target
 * are hypothetical and never sent to a broker. Every threshold shown comes from the route's `rules` block; none is kept here.
 */
import { useId, useState, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorBlock, LoadingBlock, Pill, fmtNum, fmtPct, type Tone } from "../../components/ui";
import { useLiveOverlay } from "../../lib/useLiveQuotes";
import { SymbolCell } from "../desk/parts";
import { fmtDay, fmtPrice } from "../trading/parts";
import { TrustLine } from "./trust";
import { Widget } from "./widget";
import {
  DEFAULT_NEAR, NEAR_CHOICES, useReversalCandidates,
  type NearPct, type Quadrant, type ReversalComponent, type ReversalData, type ReversalRow, type ReversalStatus,
} from "./reversal-data";

const NEAR_PARAM = "sc_near";
const ALL_PARAM = "sc_revall";

export const STATUS_TEXT: Record<ReversalStatus, { label: string; plain: string; tone: Tone }> = {
  confirmed: { label: "Confirmed breakout", plain: "Broke out", tone: "mint" },
  trigger_ready: { label: "Trigger ready", plain: "Close to breaking out", tone: "mint" },
  early_reversal: { label: "Early reversal", plain: "Early turn", tone: "indigo" },
  watchlist: { label: "Watchlist · low coverage", plain: "Watch only", tone: "amber" },
  near_low_no_evidence: { label: "Near low · no evidence", plain: "Not turning yet", tone: "ink" },
  excluded: { label: "Excluded", plain: "Excluded", tone: "danger" },
};

export const EXCLUSION_TEXT: Record<string, string> = {
  insufficient_history: "Under 252 sessions of price history",
  illiquid: "Below the traded-value floor",
  no_traded_value: "No 20-session traded value",
  scanner_etf: "ETF",
  scanner_series: "Series not eligible",
  scanner_price_band: "Tight price band",
  scanner_at_band_limit: "Closed at a price-band limit",
  scanner_missing_price: "Price missing",
  scanner_no_reference: "No exchange reference row",
  high_pledge: "High promoter pledge",
  financial_distress: "Financial distress",
  setup_invalidated: "Setup invalidated (broke support)",
  above_pool: "Further above the low than the chosen threshold",
};

const QUADRANT_TEXT: Record<Quadrant, { label: string; tone: Tone }> = {
  leading: { label: "Leading", tone: "mint" },
  improving: { label: "Improving", tone: "indigo" },
  weakening: { label: "Weakening", tone: "amber" },
  lagging: { label: "Lagging", tone: "danger" },
  unknown: { label: "Unknown", tone: "ink" },
};

const COMPONENT_TEXT: Record<string, string> = {
  sector: "Sector rotation", technical: "Technical setup", momentum: "Stock momentum",
  fundamental: "Fundamental quality", catalyst: "Catalysts & events", valuation_risk: "Valuation & downside risk",
};

const SIGNAL_TEXT: Record<string, string> = {
  higher_low: "Higher low", low_not_new: "No new low", rsi_recovery: "RSI recovering", ema20_reclaim: "Back above EMA20",
  rs_vs_index: "Beats the index", volume_participation: "Buyers on volume", above_ema50: "Above EMA50", roc5: "5-session return", roc20: "20-session return",
};

const label = (m: Record<string, string>, k: string) => m[k] ?? k.replace(/_/g, " ");
const small: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const mono: CSSProperties = { fontFamily: "var(--mono)" };
const rowBorder = "1px solid var(--cp-line)";

function useNear(): { near: NearPct; all: boolean; setNear: (n: NearPct) => void; setAll: (v: boolean) => void } {
  const [params, setParams] = useSearchParams();
  const n = Number(params.get(NEAR_PARAM));
  const near = (NEAR_CHOICES as readonly number[]).includes(n) ? (n as NearPct) : DEFAULT_NEAR;
  const patch = (k: string, v: string | null) => setParams((prev) => { const p = new URLSearchParams(prev); if (v == null) p.delete(k); else p.set(k, v); return p; }, { replace: true });
  return { near, all: params.get(ALL_PARAM) === "1", setNear: (x) => patch(NEAR_PARAM, x === DEFAULT_NEAR ? null : String(x)), setAll: (v) => patch(ALL_PARAM, v ? "1" : null) };
}

function Score({ r }: { r: ReversalRow }) {
  if (r.total == null) return <span data-testid="desk-rev-score" style={{ color: "var(--cp-ink-4)" }}>—</span>;
  return (
    <span data-testid="desk-rev-score" title={`Rule-based score of the ${fmtNum(r.coveragePct)}% of the 100 points that could be measured. Not a probability.`}>
      <span style={{ ...mono, fontSize: 20, color: "var(--cp-ink)" }}>{fmtNum(r.total)}</span>
      <span style={{ ...small, marginLeft: 6 }}>{fmtNum(r.coveragePct)}% scored</span>
    </span>
  );
}

function Fig({ k, c }: { k: string; c: ReversalComponent | undefined }) {
  return (
    <span data-testid={`desk-rev-fig-${k}`} data-known={c?.known ? "true" : "false"} title={c?.note ?? undefined} style={{ display: "inline-flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
      <span className="cp-eyebrow" style={{ fontSize: 9 }}>{label(COMPONENT_TEXT, k)}</span>
      {c?.known ? <span style={{ ...mono, fontSize: 13 }}>{fmtNum(c.score)}</span> : <span style={{ fontSize: 13, color: "var(--cp-ink-4)" }}>Unknown</span>}
    </span>
  );
}

function SectorPill({ r }: { r: ReversalRow }) {
  const q = r.sector?.quadrant ?? "unknown";
  const t = QUADRANT_TEXT[q];
  const tip = r.sector
    ? `${r.industry ?? "Sector"}: relative strength ${r.sector.rs == null ? "—" : fmtPct(r.sector.rs, { signed: true, digits: 1 })} vs the benchmark, ${r.sector.change == null ? "change unknown" : `${fmtPct(r.sector.change, { signed: true, digits: 1 })} over 10 sessions`}, ${r.sector.breadth == null ? "breadth unknown" : `${fmtNum(r.sector.breadth)}% above the 50-day average`}`
    : "No sector context: the data platform does not classify this stock's industry.";
  return <span data-testid="desk-rev-sector" data-quadrant={q}><Pill tone={t.tone} title={tip}>{r.sector ? `Sector ${t.label.toLowerCase()}` : "Sector unknown"}</Pill></span>;
}

function Detail({ r, asOf }: { r: ReversalRow; asOf: string | null }) {
  // Kite's live price while the feed is LIVE (after the close, its closing quote until the scan's own day catches up),
  // shown beside the scan's close. The levels themselves stay the scan's.
  const live = useLiveOverlay(r.symbol, asOf);
  const h = (t: string) => <span className="cp-eyebrow" style={{ fontSize: 9, display: "block", marginBottom: 4 }}>{t}</span>;
  return (
    <div data-testid="desk-rev-detail" style={{ display: "grid", gap: 14, padding: "12px 0 4px", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
      <div>
        {h("Why this stock")}
        <p style={{ ...small, margin: 0 }} data-testid="desk-rev-why">{r.why.thisStock ?? "—"}</p>
        {h("Why now")}
        <p style={{ ...small, margin: 0 }}>{r.why.now ?? "—"}</p>
        {h("What would invalidate it")}
        <p style={{ ...small, margin: 0 }} data-testid="desk-rev-invalidates">{r.why.invalidates ?? "—"}</p>
        {h("Entry trigger (hypothetical)")}
        <p style={{ ...small, margin: 0 }}>{r.why.trigger ?? "—"}</p>
      </div>
      <div>
        {h("What remains uncertain")}
        <ul data-testid="desk-rev-uncertain" style={{ ...small, margin: 0, paddingLeft: 16 }}>
          {r.why.uncertain.length ? r.why.uncertain.map((u) => <li key={u}>{u}</li>) : <li>Nothing flagged.</li>}
        </ul>
        {h("Stabilization evidence")}
        <ul data-testid="desk-rev-signals" style={{ ...small, margin: 0, paddingLeft: 16 }}>
          {r.signals.map((s) => (
            <li key={s.key} data-state={s.state}>
              <b style={{ color: s.state === "true" ? "var(--mint)" : s.state === "false" ? "var(--cp-danger)" : "var(--cp-ink-4)" }}>{s.state === "true" ? "Yes" : s.state === "false" ? "No" : "Unknown"}</b>
              {" · "}{label(SIGNAL_TEXT, s.key)}{s.observed ? ` (${s.observed})` : ""}
            </li>
          ))}
        </ul>
      </div>
      <div>
        {h("Score parts (weights are untuned hypotheses)")}
        <ul data-testid="desk-rev-components" style={{ ...small, margin: 0, paddingLeft: 16 }}>
          {r.components.map((c) => (
            <li key={c.key} data-known={c.known ? "true" : "false"}>
              {label(COMPONENT_TEXT, c.key)} ({fmtNum(c.weight)} pts): <b>{c.known ? fmtNum(c.score) : "Unknown"}</b>{c.note ? ` — ${c.note}` : ""}
            </li>
          ))}
        </ul>
        {h("Levels (hypothetical, not sent to a broker)")}
        <p style={{ ...small, margin: 0 }} data-testid="desk-rev-levels">
          Close {fmtPrice(r.levels.close)}{live ? <b data-testid="desk-rev-live" data-kind={live.kind} style={{ color: "var(--mint)", fontWeight: 500 }}> · {live.kind === "live" ? "live" : "Kite close"} {fmtPrice(live.ltp)}{live.kind === "live" ? " (Kite)" : ""}</b> : null} · trigger {fmtPrice(r.levels.resistance)} · invalidation {fmtPrice(r.levels.invalidation)} · target {fmtPrice(r.levels.target)} · reward/risk {r.levels.rewardRisk == null ? "—" : fmtNum(r.levels.rewardRisk, 2)}
        </p>
      </div>
    </div>
  );
}

function Card({ r, selected, onOpen, plain, asOf }: { r: ReversalRow; selected: boolean; onOpen: (s: string) => void; plain: boolean; asOf: string | null }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const st = STATUS_TEXT[r.status];
  const comp = (k: string) => r.components.find((c) => c.key === k);
  return (
    <li data-testid="desk-rev-row" data-symbol={r.symbol} data-status={r.status} style={{ listStyle: "none", padding: "12px 18px", borderTop: rowBorder, background: selected ? "var(--bg-2)" : undefined }}>
      <div className="flex flex-wrap items-center" style={{ gap: "8px 16px" }}>
        <button type="button" onClick={() => onOpen(r.symbol)} aria-label={`Open ${r.symbol} chart`} style={{ border: 0, background: "none", padding: 0, cursor: "pointer", textAlign: "left", minWidth: 150 }}>
          <SymbolCell symbol={r.symbol} sub={r.industry ?? undefined} testId="desk-rev-symbol"><span style={{ ...mono, fontSize: 12.5 }}>{r.symbol}</span></SymbolCell>
        </button>
        <span data-testid="desk-rev-status"><Pill tone={st.tone}>{plain ? st.plain : st.label}</Pill></span>
        <span data-testid="desk-rev-distance" style={{ ...small, color: "var(--cp-ink-2)" }}>{fmtPct(r.distancePct, { digits: 1 })} above the 52-week low{r.low52w != null ? ` (${fmtPrice(r.low52w)}${r.lowDate ? `, ${fmtDay(r.lowDate)}` : ""})` : ""}</span>
        <SectorPill r={r} />
        <span style={{ marginLeft: "auto" }}><Score r={r} /></span>
      </div>
      <div className="flex flex-wrap items-end" style={{ gap: "8px 22px", marginTop: 8 }}>
        <Fig k="fundamental" c={comp("fundamental")} />
        <Fig k="catalyst" c={comp("catalyst")} />
        <Fig k="technical" c={comp("technical")} />
        <span data-testid="desk-rev-evidence" style={small}>{r.coreTrue ?? "—"} of {r.coreTotal ?? "—"} stabilization signals{r.requiredTrue != null ? ` (needs ${r.requiredTrue})` : ""}</span>
        <span data-testid="desk-rev-invalidation" style={{ ...small, marginLeft: "auto" }}>Invalidation <b style={{ ...mono, color: "var(--cp-ink)" }}>{r.levels.invalidation == null ? "Unknown" : fmtPrice(r.levels.invalidation)}</b></span>
        <button type="button" data-testid="desk-rev-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}
          style={{ padding: "4px 10px", borderRadius: 999, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink-2)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)" }}>
          {open ? "Hide detail ▴" : "Why ▾"}
        </button>
      </div>
      {r.warnings.length > 0 && (
        <ul data-testid="desk-rev-warnings" style={{ margin: "8px 0 0", padding: 0 }}>
          {r.warnings.map((w) => <li key={w.code} data-code={w.code} role="status" style={{ listStyle: "none", fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>⚠ {w.detail}</li>)}
        </ul>
      )}
      <div id={id} hidden={!open}>{open && <Detail r={r} asOf={asOf} />}</div>
    </li>
  );
}

function Exclusions({ d }: { d: ReversalData }) {
  const entries = Object.entries(d.universe.exclusions).sort((a, b) => b[1] - a[1]);
  const list = d.excluded;
  return (
    <details data-testid="desk-rev-excluded" style={{ ...small, padding: "10px 18px", borderTop: rowBorder }}>
      <summary style={{ cursor: "pointer", color: "var(--cp-ink-2)" }}>
        {fmtNum(entries.reduce((n, [, c]) => n + c, 0))} stocks left out, with the reason for each
      </summary>
      <p data-testid="desk-rev-exclusion-counts" style={{ margin: "6px 0" }}>
        {entries.map(([k, n]) => `${label(EXCLUSION_TEXT, k)}: ${fmtNum(n)}`).join(" · ") || "None."}
      </p>
      {list.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {list.map((x) => <li key={x.symbol} data-testid="desk-rev-excluded-row"><b style={mono}>{x.symbol}</b> — {label(EXCLUSION_TEXT, x.exclusion ?? "excluded")}{x.distancePct != null ? ` · ${fmtPct(x.distancePct, { digits: 1 })} above the low` : ""}</li>)}
        </ul>
      )}
    </details>
  );
}

function SectorStrip({ d }: { d: ReversalData }) {
  const shown = d.sectors.filter((s) => s.rs != null).slice(0, 12);
  return (
    <div data-testid="desk-rev-sectors" style={{ padding: "10px 18px", borderTop: rowBorder }}>
      <span className="cp-eyebrow" style={{ fontSize: 9, display: "block", marginBottom: 6 }}>Sector rotation · median 20-session return vs {d.benchmark ?? "the benchmark"}, change over 10 sessions</span>
      <span className="flex flex-wrap" style={{ gap: 6 }}>
        {shown.map((s) => {
          const q = QUADRANT_TEXT[s.quadrant];
          return (
            <span key={s.industry} data-testid="desk-rev-sector-chip" data-quadrant={s.quadrant} title={`${s.stocks ?? "—"} stocks · ${s.breadth == null ? "breadth unknown" : `${fmtNum(s.breadth)}% above the 50-day average`}`}>
              <Pill tone={q.tone}>{s.industry} · {q.label} {s.rs == null ? "" : fmtPct(s.rs, { signed: true, digits: 1 })}</Pill>
            </span>
          );
        })}
        {shown.length === 0 && <span style={small}>Sector rotation is unknown for every sector in this scan.</span>}
      </span>
    </div>
  );
}

export default function ReversalPanel({ chips, plain, selected, onOpen }: { chips: ReactNode; plain: boolean; selected: string | null; onOpen: (s: string) => void }) {
  const { near, all, setNear, setAll } = useNear();
  const q = useReversalCandidates(near, all);
  const d = q.data;
  const rules = d?.rulesVersion;
  const counts = d?.universe.statusCounts ?? {};
  const cand = (counts.confirmed ?? 0) + (counts.trigger_ready ?? 0) + (counts.early_reversal ?? 0) + (counts.watchlist ?? 0);
  return (
    <Widget id="scanner.reversal" testId="desk-scanner" data={{ "data-layout": "desk", "data-cat": "reversal" }} num="02" title="AI Opportunity scanner · Reversal candidates">
      <div style={{ padding: "10px 18px", borderBottom: rowBorder }}>
        <TrustLine testId="desk-rev-trust" source={d?.source ?? "NIDP feature store · NSE end-of-day prices"} mode="eod" asOf={d ? fmtDay(d.asOf) : null} maker="rules"
          method={rules ?? null} status={q.isError ? "failed" : "ok"} />
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 12, padding: "12px 18px", borderBottom: rowBorder }}>
        <span style={{ flex: "1 1 360px", minWidth: 0 }}>{chips}</span>
        <span className="inline-flex items-center" role="group" aria-label="Distance from the 52-week low" style={{ gap: 6, ...small }}>
          Within
          {NEAR_CHOICES.map((n) => (
            <button key={n} type="button" data-testid={`desk-rev-near-${n}`} aria-pressed={n === near} onClick={() => setNear(n)}
              style={{ padding: "4px 10px", borderRadius: 999, border: `1px solid ${n === near ? "var(--mint-line)" : "var(--line-2)"}`, background: n === near ? "var(--mint-soft)" : "transparent", color: n === near ? "var(--mint)" : "var(--cp-ink-2)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)" }}>
              {n}%
            </button>
          ))}
          of the low
        </span>
        <label className="inline-flex items-center" style={{ gap: 6, ...small }}>
          <input type="checkbox" data-testid="desk-rev-all" checked={all} onChange={(e) => setAll(e.target.checked)} />
          Also show near-low stocks with no evidence
        </label>
      </div>
      <div data-testid="desk-rev-rule" style={{ ...small, padding: "10px 18px", borderBottom: rowBorder }}>
        <span className="cp-eyebrow" style={{ fontSize: 9, marginRight: 8 }}>Reversal · rule</span>
        Within {near}% of the lowest low of the last 252 sessions — (close ÷ low − 1) × 100. Being near the low is only a screen. A stock is a candidate when at
        least {d?.rows[0]?.requiredTrue ?? 3} of 6 independent signals confirm stabilization: a higher low, no new low for 5+ sessions, RSI recovering, price back above a rising EMA20,
        outperforming the Nifty 500, and buyers outweighing sellers on volume. Hard gates (liquidity, pledge, distress, broken support) remove a stock whatever its score.
        {rules ? <span className="cp-mono-note" data-testid="desk-rev-rules-version"> · {rules}</span> : null}
      </div>

      {q.isPending && <div style={{ padding: 18 }}><LoadingBlock label="Loading reversal candidates" rows={4} /></div>}
      {q.isError && !d && <div data-testid="desk-rev-error" style={{ padding: 18 }}><ErrorBlock title="Reversal candidates didn’t load" error={q.error} onRetry={() => q.refetch()} /></div>}
      {d && (
        <>
          <div data-testid="desk-rev-summary" style={{ ...small, padding: "10px 18px", color: "var(--cp-ink-2)" }}>
            {fmtNum(d.universe.evaluated)} liquid stocks checked on {fmtDay(d.asOf)}: <b>{fmtNum(cand)}</b> reversal candidates, {fmtNum(counts.near_low_no_evidence ?? 0)} near the low without enough evidence, {fmtNum(counts.excluded ?? 0)} left out by a hard gate
            {d.prefilter?.droppedIlliquid ? `; ${fmtNum(d.prefilter.droppedIlliquid)} more near-low stocks were below the traded-value floor before the checks` : ""}.
          </div>
          <SectorStrip d={d} />
          {d.rows.length === 0 ? (
            <div data-testid="desk-rev-empty" style={{ padding: "14px 18px", fontSize: 13, color: "var(--cp-ink-3)", borderTop: rowBorder }}>No stock within {near}% of its 52-week low shows enough stabilization evidence on this scan.</div>
          ) : (
            <ul data-testid="desk-rev-list" aria-label="Reversal candidates" style={{ margin: 0, padding: 0 }}>
              {d.rows.map((r) => <Card key={r.symbol} r={r} selected={selected?.toUpperCase() === r.symbol} onOpen={onOpen} plain={plain} asOf={d.asOf} />)}
            </ul>
          )}
          {d.truncated && <div style={{ ...small, padding: "8px 18px" }}>The list is capped; the lowest-ranked rows are not shown.</div>}
          <Exclusions d={d} />
          <div data-testid="desk-rev-footnote" className="flex flex-col" style={{ gap: 4, padding: "12px 18px", borderTop: rowBorder, ...small }}>
            <span>
              The score is rule-based: six parts with untuned hypothesis weights ({Object.entries(d.weights).map(([k, v]) => `${label(COMPONENT_TEXT, k).toLowerCase()} ${fmtNum(v)}`).join(", ") || "—"}). It ranks setups; it is not a probability and has not been validated out of sample.
              A part that could not be measured says Unknown and is left out of the total (the percentage scored shows how much was measured). Entry trigger, invalidation and target are hypothetical and are never sent to a broker. Research and paper trading only.
            </span>
            {d.dataLimits.map((x) => <span key={x} data-testid="desk-rev-limit">• {x}</span>)}
            <span>Source: {d.source ?? "—"}.</span>
          </div>
        </>
      )}
    </Widget>
  );
}
