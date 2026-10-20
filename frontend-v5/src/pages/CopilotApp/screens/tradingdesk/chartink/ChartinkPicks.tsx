/**
 * Best picks from the user's Chartink scans - the pieces the Chartink settings, the Overview card and the Strategy Builder's ideas board share.
 *
 *   <ChartinkPicks variant="full">   the whole list: picks with their evidence score, factors, reasons for and against, strategies; then Wait / No trade
 *   <ChartinkPicks variant="top">    the Overview's sub-section: the first 3 picks and a "See all" link to the full list
 *
 * Every figure is the route's (GET /api/desk/chartink/picks): the score ("evidence score - not a probability"), each factor's points, state, source and
 * as-of, and each strategy's payoff figures. Nothing is scored, ranked or recalculated here. A strategy row opens to its legs and risk figures and draws
 * its payoff through the payoff engine (POST /api/desk/strategy/payoff, a pure calculation); "Open in Strategy Builder" hands the pick's own plan inputs
 * to the Strategy Builder. Nothing here places an order.
 */
import { useId, useState, type CSSProperties } from "react";
import { StockIcon } from "../../../components/EntityIcon";
import { Btn, ErrorBlock, LoadingBlock, Pill, fmtNum, humaniseTag, type Tone } from "../../../components/ui";
import { useCopilotShell } from "../../../lib/shell-context";
import { fmtDay } from "../../trading/parts";
import { useDesk } from "../context";
import { stampIst } from "../overview-data";
import { TrustLine } from "../trust";
import { PayoffChart } from "../strategy/PayoffChart";
import { DASH, noteStyle, ratio, rupees, rupeesAbs } from "../strategy/plan-format";
import { paramsFromPlanInputs } from "../strategy/ideas-data";
import { usePayoff } from "../strategy/usePayoff";
import { CHARTINK_SOURCE_LABEL } from "./ChartinkParts";
import { useChartinkSource } from "./chartink-data";
import type { ChartinkPicks, FactorState, Pick, PickFactor, PickStrategy } from "./picks-contract";
import { useChartinkPicks } from "./picks-data";

const line = "1px solid var(--cp-line)";
const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)", fontFamily: "var(--sans)", textAlign: "left" };
export const PICKS_TITLE = "Best picks from my Chartink scans";
export const TOP_PICKS = 3;

const FACTOR_LOOK: Record<FactorState, { tone: Tone; glyph: string; word: string }> = {
  supports: { tone: "mint", glyph: "↑", word: "Supports" },
  neutral: { tone: "ink", glyph: "–", word: "Neutral" },
  conflicts: { tone: "danger", glyph: "↓", word: "Conflicts" },
  unavailable: { tone: "amber", glyph: "?", word: "Unavailable" },
  not_applicable: { tone: "ink", glyph: "·", word: "Not applicable" },
};
const STRATEGY_STATUS: Record<string, { label: string; tone: Tone; glyph: string }> = {
  candidate: { label: "Viable", tone: "mint", glyph: "✓" },
  wait: { label: "Wait", tone: "amber", glyph: "◔" },
  no_trade: { label: "No trade", tone: "danger", glyph: "✕" },
  avoid: { label: "Avoid", tone: "danger", glyph: "⊘" },
  insufficient_data: { label: "Insufficient data", tone: "ink", glyph: "?" },
};
const OUTCOME_WORD = { wait: "Wait", no_trade: "No trade", pick: "Pick" } as const;
const STATE_NOTE: Record<string, string> = {
  no_source: "No Chartink dashboard is connected.",
  not_refreshed: "Your Chartink scans have not been refreshed yet, so there is nothing to pick from.",
  stale: "The latest Chartink hits are too old to pick from.",
  failed: "The Chartink hits could not be read.",
};

const pts = (n: number) => fmtNum(n, Number.isInteger(n) ? 0 : 1);

// ── the factor chips and the breakdown ───────────────────────────────────

function FactorChip({ f }: { f: PickFactor }) {
  const w = FACTOR_LOOK[f.state];
  const shown = f.state === "unavailable" || f.state === "not_applicable" ? w.word.toLowerCase() : `${pts(f.points)}/${pts(f.weight)}`;
  return (
    <span data-testid="ck-pick-factor" data-key={f.key} data-state={f.state} title={`${f.text}${f.source ? ` · ${f.source}` : ""}${f.as_of ? ` · as of ${f.as_of}` : ""}`} style={{ display: "inline-flex", maxWidth: "100%" }}>
      <Pill tone={w.tone}><span aria-hidden>{w.glyph} </span><span style={{ overflowWrap: "anywhere" }}>{f.label.replace(/ \(.*\)$/, "")} {shown}</span><span className="sr-only"> ({w.word})</span></Pill>
    </span>
  );
}

function Breakdown({ factors }: { factors: PickFactor[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <button type="button" data-testid="ck-pick-breakdown-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} style={{ ...linkBtn, color: "var(--cp-ink-2)", alignSelf: "flex-start" }}>
        {open ? "▾" : "▸"} How the score is built ({factors.length} factors)
      </button>
      <ul id={id} hidden={!open} data-testid="ck-pick-breakdown" className="m-0 min-w-0 flex-col p-0" style={{ listStyle: "none", gap: 8, display: open ? "flex" : "none" }}>
        {factors.map((f) => (
          <li key={f.key} data-testid="ck-pick-breakdown-row" data-key={f.key} style={{ fontSize: 12.5, lineHeight: 1.5 }}>
            <b style={{ fontWeight: 500 }}>{f.label}</b> · {FACTOR_LOOK[f.state].word} · {f.state === "not_applicable" ? "left out of the weight" : `${pts(f.points)} of ${pts(f.weight)}`}
            <span style={{ display: "block", color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{f.text}</span>
            <span style={{ display: "block", ...noteStyle, overflowWrap: "anywhere" }}>{f.source ?? "no source"}{f.as_of ? ` · as of ${f.as_of}` : ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Reasons({ pick }: { pick: Pick }) {
  const list = (kind: string, title: string, items: Pick["reasons_for"], tone: string) => items.length === 0 ? null : (
    <div data-testid={`ck-pick-${kind}`} className="flex min-w-0 flex-col" style={{ gap: 3 }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5, color: tone }}>{title}</span>
      <ul className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16 }}>
        {items.map((r) => <li key={r.key} data-key={r.key} style={{ fontSize: 12.5, lineHeight: 1.5, overflowWrap: "anywhere" }}><b style={{ fontWeight: 500 }}>{r.label}:</b> {r.text}</li>)}
      </ul>
    </div>
  );
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      {list("for", "Why it ranks", pick.reasons_for.slice(0, 4), "var(--mint)")}
      {list("against", "Against it", pick.reasons_against, "var(--cp-danger)")}
      {list("unavailable", "Could not be read (earns nothing, never counted as neutral)", pick.unavailable, "var(--amber)")}
    </div>
  );
}

// ── strategies ───────────────────────────────────────────────────────────

function PickPayoff({ s, compact }: { s: PickStrategy; compact: boolean }) {
  const { persona } = useDesk();
  const q = usePayoff(s.payoff_request, { debounceMs: 0 });
  if (!s.payoff_request) return null;
  if (q.errorText && !q.data) return <p role="alert" data-testid="ck-pick-payoff-error" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>{q.errorText} <button type="button" onClick={q.refetch} style={linkBtn}>Retry ›</button></p>;
  if (!q.data) return <span role="status" data-testid="ck-pick-payoff-loading" style={noteStyle}>Drawing the payoff…</span>;
  return (
    <div data-testid="ck-pick-payoff" className="min-w-0" style={{ maxWidth: "100%" }}>
      <PayoffChart expiry={q.data.expiry} preExpiry={null} referencePrice={s.payoff_request.reference_price} compact={compact} stale={q.isStale} persona={persona} />
      <span style={noteStyle}>Payoff at expiry from the payoff engine, net of the costs shown in the Strategy Builder; a calculation, not a forecast.</span>
    </div>
  );
}

function StrategyRow({ s, pick, preferred, compact, onOpen }: { s: PickStrategy; pick: Pick; preferred: boolean; compact: boolean; onOpen: (cand: string) => void }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const viable = s.status === "candidate";
  const w = STRATEGY_STATUS[s.status] ?? { label: humaniseTag(s.status), tone: "ink" as Tone, glyph: "?" };
  const sz = s.sizing;
  const sizing = !viable ? DASH : sz?.lots != null ? `${fmtNum(sz.lots)} lot${sz.lots === 1 ? "" : "s"}${sz.quantity != null ? ` (${fmtNum(sz.quantity)} units)` : ""}` : sz?.quantity != null ? `${fmtNum(sz.quantity)} shares` : DASH;
  const flags = [...s.liquidity_flags, ...s.flags].map((f) => (typeof f === "string" ? f : JSON.stringify(f)));
  const fact = (k: string, label: string, v: string, tid: string) => <div key={k} className="flex min-w-0 flex-col" style={{ gap: 1 }}><span className="cp-mono-note">{label}</span><span data-testid={tid} className="cp-num" style={{ fontSize: 12.5, overflowWrap: "anywhere" }}>{v}</span></div>;
  return (
    <li data-testid="ck-pick-strategy" data-id={s.id} data-status={s.status} data-preferred={preferred} style={{ borderTop: line }}>
      <button type="button" data-testid="ck-pick-strategy-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} className="grid w-full"
        style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "2px 10px", padding: "9px 0", border: 0, background: "transparent", color: "inherit", textAlign: "left", cursor: "pointer", fontFamily: "var(--sans)" }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
          <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "2px 8px" }}>
            <span aria-hidden>{open ? "▾" : "▸"}</span>
            <span style={{ fontSize: 13, fontWeight: 500, overflowWrap: "anywhere" }}>{s.label}</span>
            {preferred && <span data-testid="ck-pick-preferred" className="cp-mono-note" style={{ color: "var(--mint)" }}>★ preferred</span>}
          </span>
          <span data-testid="ck-pick-strategy-summary" className="cp-num" style={{ fontSize: 11.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
            {viable ? `Max loss ${rupeesAbs(s.max_loss)} · Max profit ${s.profit_unbounded ? "unlimited" : rupees(s.max_profit)} · Reward : risk ${ratio(s.reward_risk_net)} net` : (s.reasons[0]?.message ?? s.why ?? DASH)}
          </span>
        </span>
        <span data-testid="ck-pick-strategy-status" style={{ alignSelf: "start" }}><Pill tone={w.tone}><span aria-hidden>{w.glyph} </span>{w.label}</Pill></span>
      </button>
      <div id={id} hidden={!open} data-testid="ck-pick-strategy-detail" className="min-w-0 flex-col" style={{ gap: 10, padding: "2px 0 12px 16px", display: open ? "flex" : "none" }}>
        {open && (
          <>
            <p data-testid="ck-pick-strategy-legs" className="m-0" style={{ fontSize: 12.5, overflowWrap: "anywhere" }}>{s.legs_text || DASH}</p>
            {s.why && <p className="m-0" style={noteStyle}>{s.why}</p>}
            {viable ? (
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,130px),1fr))", gap: "8px 14px" }}>
                {fact("ml", "Max loss", `${rupeesAbs(s.max_loss)}${s.max_loss_basis ? ` (${s.max_loss_basis})` : ""}`, "ck-pick-st-maxloss")}
                {fact("cap", "Capital at risk", rupees(s.capital_at_risk), "ck-pick-st-capital")}
                {fact("rr", "Reward : risk", `${ratio(s.reward_risk_net)} net · ${ratio(s.reward_risk_gross)} gross`, "ck-pick-st-rr")}
                {fact("mp", "Max profit", s.profit_unbounded ? "Unlimited" : rupees(s.max_profit), "ck-pick-st-maxprofit")}
                {fact("be", "Breakeven", s.breakeven.length ? s.breakeven.map((b) => fmtNum(b, 2)).join(", ") : DASH, "ck-pick-st-breakeven")}
                {fact("sz", "Sizing", sizing, "ck-pick-st-sizing")}
                {fact("mg", "Margin", `${DASH} not estimated: no margin source exists`, "ck-pick-st-margin")}
              </div>
            ) : (
              s.reasons.length > 0 && <ul className="m-0" style={{ paddingLeft: 16, fontSize: 12, color: "var(--cp-ink-2)" }}>{s.reasons.map((r) => <li key={r.code + r.message}>{r.message}</li>)}</ul>
            )}
            {viable && flags.length > 0 && <p data-testid="ck-pick-st-flags" className="m-0" style={{ fontSize: 12, color: "var(--amber)" }}>Flags: {flags.join("; ")}</p>}
            {viable && s.segment === "futures" && <p className="m-0" style={noteStyle}>A loss on futures can exceed the margin.</p>}
            {viable && <PickPayoff s={s} compact={compact} />}
            <div>
              <Btn variant="primary" data-testid="ck-pick-open-builder" aria-label={`Open ${pick.symbol} ${s.label} in Strategy Builder`} onClick={() => onOpen(s.id)} style={{ padding: "6px 12px", fontSize: 12 }}>Open in Strategy Builder ›</Btn>
            </div>
          </>
        )}
      </div>
    </li>
  );
}

function Strategies({ pick, compact, onOpen }: { pick: Pick; compact: boolean; onOpen: (cand: string) => void }) {
  const noFno = pick.strategies.filter((r) => r.reasons.some((x) => x.code === "not_fno_eligible"));
  const rows = pick.strategies.filter((r) => !noFno.includes(r));
  return (
    <div data-testid="ck-pick-strategies" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Strategies from the Strategy Builder ({rows.filter((r) => r.status === "candidate").length} viable of {rows.length})</span>
      {noFno.length > 0 && <p role="note" data-testid="ck-pick-not-fno" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>No futures and options for this stock: only cash applies.</p>}
      {rows.length === 0 ? <p data-testid="ck-pick-no-strategies" className="m-0" style={noteStyle}>No strategy was built for this pick.</p> : (
        <ul className="m-0 flex min-w-0 flex-col p-0" style={{ listStyle: "none" }}>
          {rows.map((s) => <StrategyRow key={s.id} s={s} pick={pick} preferred={pick.preferred === s.id} compact={compact} onOpen={onOpen} />)}
        </ul>
      )}
    </div>
  );
}

// ── one pick ─────────────────────────────────────────────────────────────

function ScanNames({ pick }: { pick: Pick }) {
  const names = pick.scans.aligned.map((x) => x.name).join(", ");
  const opposed = pick.scans.opposed.map((x) => x.name).join(", ");
  return (
    <p data-testid="ck-pick-scans" className="m-0" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
      On your Chartink {pick.scans.aligned.length === 1 ? "scan" : "scans"}: {names || DASH}{opposed ? <span style={{ color: "var(--cp-danger)" }}> · against: {opposed}</span> : null}
    </p>
  );
}

function PickCard({ pick, asOf, scanDate, chartinkMode, rulesVersion, compact }: { pick: Pick; asOf: string | null; scanDate: string | null; chartinkMode: string | null; rulesVersion: string | null; compact: boolean }) {
  const { openStrategyPlan, openChart } = useDesk();
  const { mobile } = useCopilotShell();
  const short = pick.direction === "short";
  const open = (cand: string) => openStrategyPlan({ ...paramsFromPlanInputs(pick.plan_inputs ?? {}), sym: pick.symbol, cand, src_kind: "chartink_picks", ...(scanDate ? { src_date: scanDate } : {}) });
  return (
    <article data-testid="ck-pick" data-symbol={pick.symbol} data-rank={pick.rank ?? ""} data-direction={pick.direction ?? ""} data-outcome={pick.outcome} className="cp-card flex min-w-0 flex-col"
      style={{ gap: 12, padding: compact ? 12 : 16 }} aria-label={`${pick.symbol} ${pick.name ?? ""}`.trim()}>
      <div className="flex flex-wrap items-start justify-between" style={{ gap: "8px 12px" }}>
        <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px" }}>
          <span className="cp-num" data-testid="ck-pick-rank" style={{ fontSize: 11, color: pick.rank === 1 ? "var(--mint)" : "var(--cp-ink-3)" }}>{pick.rank != null ? String(pick.rank).padStart(2, "0") : ""}</span>
          <StockIcon symbol={pick.symbol} name={pick.name} size={compact ? 22 : 26} />
          <button type="button" data-testid="ck-pick-symbol" onClick={() => openChart(pick.symbol)} aria-label={`${pick.symbol}: open its chart analysis`} className="cp-num"
            style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: compact ? 14 : 16, fontWeight: 500, color: "inherit", fontFamily: "inherit" }}>{pick.symbol}</button>
          {pick.name && <span data-testid="ck-pick-name" style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{pick.name}</span>}
          <span data-testid="ck-pick-direction" data-direction={pick.direction ?? ""}>
            <Pill tone={short ? "danger" : "mint"}>{pick.direction == null ? "No direction" : short ? "Short side" : "Long"}</Pill>
          </span>
          <span data-testid="ck-pick-source" title={pick.source === "both" ? "Listed by the AI scanner and by your Chartink scans" : "From your Chartink scans; the AI scanner does not list it"}>
            <Pill tone="indigo">{pick.source === "both" ? "AI scanner + Chartink" : "Chartink"}</Pill>
          </span>
          {pick.outcome !== "pick" && <span data-testid="ck-pick-outcome"><Pill tone={pick.outcome === "no_trade" ? "danger" : "amber"}>{OUTCOME_WORD[pick.outcome]}</Pill></span>}
        </span>
        <span className="flex flex-col items-end" style={{ gap: 1, textAlign: "right" }}>
          <span data-testid="ck-pick-score" className="cp-num" style={{ fontSize: compact ? 18 : 22, fontWeight: 500, color: pick.score != null && pick.score >= 75 ? "var(--mint)" : "var(--cp-ink)" }}>
            {pick.score == null ? DASH : pts(pick.score)}<span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>/100</span>
          </span>
          <span data-testid="ck-pick-score-label" style={{ fontSize: 10.5, color: "var(--cp-ink-3)" }}>{pick.score_label}</span>
        </span>
      </div>

      {pick.action && <p data-testid="ck-pick-action" className="m-0" style={{ fontSize: 12.5, color: short ? "var(--cp-danger)" : "var(--cp-ink-2)" }}>{pick.action}</p>}
      <ScanNames pick={pick} />
      {pick.factors.length > 0 && (
        <div data-testid="ck-pick-factors" role="group" aria-label="Evidence factors" className="flex min-w-0 flex-wrap" style={{ gap: "4px 6px" }}>
          {pick.factors.map((f) => <FactorChip key={f.key} f={f} />)}
        </div>
      )}
      {pick.available_weight_pct != null && (
        <span data-testid="ck-pick-read" style={noteStyle}>Evidence read: {pts(pick.available_weight_pct)}% of the scoring weight{pick.fno_eligible === false ? " (not an F&O stock: open interest is left out)" : ""}.</span>
      )}
      {pick.outcome !== "pick" && pick.wait_reasons.length > 0 && (
        <ul data-testid="ck-pick-wait-reasons" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16 }}>
          {pick.wait_reasons.map((r) => <li key={r} style={{ fontSize: 12.5, lineHeight: 1.5, overflowWrap: "anywhere" }}>{r}</li>)}
        </ul>
      )}
      <Reasons pick={pick} />
      {pick.factors.length > 0 && <Breakdown factors={pick.factors} />}
      {pick.outcome === "pick" && <Strategies pick={pick} compact={compact || mobile} onOpen={open} />}
      <TrustLine testId="ck-pick-trust" source={`${CHARTINK_SOURCE_LABEL}, NSE end-of-day prices and F&O, plan evidence`} mode="eod" asOf={asOf} maker="rules"
        method={[rulesVersion ? `rules ${rulesVersion}` : null, "evidence score, not a probability", "your scan rules, not validated signals", chartinkMode === "fetched_at" ? "Chartink hits as of the fetch time" : null].filter(Boolean).join(" · ")} />
    </article>
  );
}

// ── the section ──────────────────────────────────────────────────────────

function asOfText(p: ChartinkPicks): string | null {
  const c = p.data_as_of.chartink;
  const parts = [c?.scan_date ? `scan ${fmtDay(c.scan_date)}` : null, p.data_as_of.price ? `prices ${fmtDay(p.data_as_of.price)}` : null, p.data_as_of.fno ? `F&O ${fmtDay(p.data_as_of.fno)}` : null,
    c?.fetched_at ? `Chartink fetched ${stampIst(c.fetched_at)}` : null].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** Hits fetched during the session are as of the fetch time, not end of day; the prices and F&O data are end of day either way. */
function chartinkTiming(p: ChartinkPicks): string | null {
  return p.data_as_of.chartink?.mode === "fetched_at" ? "Chartink hits are as of the fetch time (the prices are end of day)" : null;
}

function WaitList({ items, testId }: { items: Pick[]; testId: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (items.length === 0) return null;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <button type="button" data-testid={`${testId}-toggle`} aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} style={{ ...linkBtn, color: "var(--cp-ink-2)", alignSelf: "flex-start" }}>
        {open ? "▾" : "▸"} Wait / No trade ({items.length}): evaluated, but not picks
      </button>
      <ul id={id} hidden={!open} data-testid={testId} className="m-0 min-w-0 flex-col p-0" style={{ listStyle: "none", gap: 8, display: open ? "flex" : "none" }}>
        {items.map((w) => (
          <li key={w.symbol} data-testid="ck-wait-row" data-symbol={w.symbol} data-outcome={w.outcome} className="flex min-w-0 flex-col" style={{ gap: 3, paddingTop: 8, borderTop: line }}>
            <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px" }}>
              <StockIcon symbol={w.symbol} name={w.name} size={20} />
              <span className="cp-num" style={{ fontSize: 13, fontWeight: 500 }}>{w.symbol}</span>
              {w.name && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{w.name}</span>}
              <Pill tone={w.outcome === "no_trade" ? "danger" : "amber"}>{OUTCOME_WORD[w.outcome]}</Pill>
              {w.score != null && <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>{pts(w.score)}/100 <span style={{ color: "var(--cp-ink-3)" }}>{w.score_label}</span></span>}
            </span>
            {w.wait_reasons.map((r) => <span key={r} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{r}</span>)}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The honest state of the list when there is nothing to rank: null while the first load is still on a dashboard check. */
function Status({ q, pad, testId }: { q: ReturnType<typeof useChartinkPicks>; pad: string; testId: string }) {
  if (q.isPending) return <div style={{ padding: pad }}><LoadingBlock label="Scoring your Chartink hits and building their strategies" rows={3} /></div>;
  if (q.isError) return <div data-testid={`${testId}-error`} style={{ padding: pad }}><ErrorBlock title="Your Chartink best picks didn’t load" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  return null;
}

export function ChartinkPicks({ variant = "full", testId = "ck-picks" }: { variant?: "full" | "top"; testId?: string }) {
  const src = useChartinkSource();
  const q = useChartinkPicks();
  const { openChartink } = useDesk();
  const { mobile } = useCopilotShell();
  const top = variant === "top";
  const pad = top ? (mobile ? "10px 14px" : "10px 18px") : "0";
  if (src.isPending || src.isError || src.data == null) return null;          // no dashboard (or it did not load): the Chartink list above already says so
  const d = q.data;
  const shown = d ? (top ? d.picks.slice(0, TOP_PICKS) : d.picks) : [];
  const asOf = d ? asOfText(d) : null;
  const header = (
    <div className="flex flex-wrap items-center justify-between" style={{ gap: "4px 12px", padding: top ? pad : 0 }}>
      <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
        <span data-testid={`${testId}-title`} className={top ? "cp-eyebrow" : "cp-display"} style={top ? undefined : { fontSize: 22, lineHeight: 1.15 }}>{PICKS_TITLE}</span>
        <span data-testid={`${testId}-sub`} style={noteStyle}>Ranked by an evidence score, not a probability. Each pick comes with strategies.</span>
      </span>
      {top && <button type="button" data-testid={`${testId}-all`} onClick={openChartink} style={linkBtn}>See all ›</button>}
    </div>
  );
  const body = (() => {
    const st = Status({ q, pad: top ? pad : "0", testId });
    if (st) return st;
    if (!d) return null;
    if (d.state !== "ok") {
      return (
        <div data-testid={`${testId}-state`} data-state={d.state} role="status" className="flex flex-col" style={{ gap: 4, padding: top ? pad : 0 }}>
          <span style={{ fontSize: 13, color: "var(--amber)" }}>{STATE_NOTE[d.state] ?? "Best picks are not available."}</span>
          {d.reason && <span style={noteStyle}>{d.reason}</span>}
          {!top && <span style={noteStyle}>{d.state === "no_source" ? "Connect a dashboard above." : "Use Refresh now above, then the picks are scored."}</span>}
        </div>
      );
    }
    return (
      <div className="flex min-w-0 flex-col" style={{ gap: 12, padding: top ? `0 ${mobile ? 14 : 18}px` : 0 }}>
        {q.isFetching && !q.isPending && <p role="status" className="m-0" style={noteStyle}>Updating…</p>}
        {d.source_failures.length > 0 && <p role="note" data-testid={`${testId}-failures`} className="m-0" style={{ fontSize: 12.5, color: "var(--amber)" }}>Source problems: {d.source_failures.map((f) => (typeof f === "string" ? f : JSON.stringify(f))).join("; ")}</p>}
        {shown.length === 0 ? (
          <div data-testid={`${testId}-empty`} className="flex flex-col" style={{ gap: 4 }}>
            <span style={{ fontSize: 13 }}>No qualifying picks right now.</span>
            <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{d.empty_reason ?? d.shortfall_reason ?? "Nothing in your Chartink hits passed the evidence rules."}</span>
          </div>
        ) : (
          <ol className="m-0 flex min-w-0 flex-col p-0" style={{ listStyle: "none", gap: 12 }}>
            {shown.map((p) => <li key={p.symbol} className="min-w-0"><PickCard pick={p} asOf={asOf} scanDate={d.data_as_of.chartink?.scan_date ?? null} chartinkMode={d.data_as_of.chartink?.mode ?? null} rulesVersion={d.rules_version} compact={top} /></li>)}
          </ol>
        )}
        {d.coverage_note && <p data-testid={`${testId}-coverage`} className="m-0" style={{ ...noteStyle, overflowWrap: "anywhere" }}>{d.coverage_note}</p>}
        {d.shortfall_reason && shown.length > 0 && <p role="note" data-testid={`${testId}-shortfall`} className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{d.shortfall_reason}</p>}
        {top && d.picks.length > shown.length && <p data-testid={`${testId}-more`} className="m-0" style={noteStyle}>{fmtNum(d.picks.length - shown.length)} more in Chartink scans · Best picks.</p>}
        {!top && <WaitList items={d.wait} testId={`${testId}-wait`} />}
        {top && d.wait.length > 0 && <p data-testid={`${testId}-wait-count`} className="m-0" style={noteStyle}>{d.wait.length} evaluated stock{d.wait.length === 1 ? "" : "s"} {d.wait.length === 1 ? "is" : "are"} Wait / No trade (reasons under See all).</p>}
        {!top && d.excluded.length > 0 && (
          <p data-testid={`${testId}-excluded`} className="m-0" style={noteStyle}>Left out by the eligibility gates: {d.excluded.map((x) => `${x.symbol} (${x.reason})`).join("; ")}.</p>
        )}
        {!top && d.ranking_note && <p data-testid={`${testId}-rule`} className="m-0" style={{ ...noteStyle, overflowWrap: "anywhere" }}>{d.ranking_note}</p>}
        {!top && d.caveats.length > 0 && <ul className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16, fontSize: 12, color: "var(--cp-ink-3)" }}>{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>}
        <TrustLine testId={`${testId}-trust`} source={`${CHARTINK_SOURCE_LABEL}, NSE end-of-day prices and F&O, plan evidence`} mode="eod" asOf={asOf} maker="rules"
          method={[d.rules_version ? `rules ${d.rules_version}` : null, "evidence score, not a probability", chartinkTiming(d)].filter(Boolean).join(" · ")} />
      </div>
    );
  })();
  return (
    <section data-testid={testId} data-variant={variant} data-state={d?.state ?? (q.isError ? "error" : "loading")} aria-label={PICKS_TITLE} className="flex min-w-0 flex-col"
      style={{ gap: top ? 8 : 12, ...(top ? { borderTop: line, background: "var(--bg-0)", paddingBottom: 12 } : {}) }}>
      {header}
      {body}
    </section>
  );
}
