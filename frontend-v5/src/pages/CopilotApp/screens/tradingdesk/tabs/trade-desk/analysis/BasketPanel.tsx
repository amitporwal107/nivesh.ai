/**
 * Chart Analysis v2 — the PAPER TRADE basket (the design's right panel; test_reports/chart_analysis_v2_TESTCASES.md U6, U8, U9).
 *
 *   ADD Cash / Future    the LAST (cash) and the future of the chain's expiry, else the near month (GET /api/fno/{sym}/futures)
 *   STRATEGY presets     legs at the chain's strikes and end-of-day closes (presets.ts)
 *   legs                 side, lots, remove; FUT / CASH entry, and STOP / TARGET on the underlying (basket levels)
 *   risk / reward        POST /api/desk/strategy/payoff: max loss / profit at expiry, or the P&L at the stop / target for a
 *                        cash / futures basket; the options' net debit or credit
 *   PLACE                POST /api/desk/paper-trades: kind "strategy" for any option or future leg, the share trade for cash
 *                        only; the route's refusal in words
 *
 * Figures are the routes'; nothing here is priced. Paper only: nothing is sent to a broker.
 */
import { useEffect, useMemo, useRef, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from "react";
import { fmtNum } from "../../../../../components/ui";
import { useFnoFutures } from "../../../../trading/fno";
import { entryRuleFor, ENTRY_RULE_SHORT } from "../../../desk-trading";
import { useBasket, legName, isOption, type BasketLeg } from "./basket";
import type { AnalysisChain } from "./chain-data";
import {
  PRESETS, STOP_SCENARIO, TARGET_SCENARIO, basketSignature, cashBodyOf, cashLeg, cashOnly, clip, familyOf, fmtExpiry, futureLeg,
  istDay, istToday, onlyUnderlying, payoffRequestOf, presetLegs, priceStep, strategyBodyOf, units,
} from "./presets";
import { useBasketPayoff, usePlaceBasket, useRegisterPlaceBuilder, type Ready } from "./basket-routes";

export interface BasketPanelProps {
  symbol: string;
  chain: AnalysisChain | null;
  notFno: string | null;
  last: { price: number; at: string; source: string };
  planLevels: { entry: number | null; stop: number | null; target: number | null; direction: string | null } | null;
  planId: string | null;
  onShowAnalysis: () => void;
  onClose: () => void;
  compact: boolean;
}

const mono = (size: number, extra: CSSProperties = {}): CSSProperties => ({ fontFamily: "var(--mono)", fontSize: size, ...extra });
const eyebrow: CSSProperties = { ...mono(10), letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--cp-ink-3)" };
const rs = (n: number | null | undefined, digits = 2) => (n == null || !Number.isFinite(n) ? "—" : `${n < 0 ? "−" : ""}₹${fmtNum(Math.abs(n), digits)}`);
const stepBtn: CSSProperties = { width: 28, height: 28, borderRadius: 7, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", cursor: "pointer", ...mono(13), flexShrink: 0 };

function Pill({ on, children, ...rest }: { on: boolean; children: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" aria-pressed={on} {...rest}
      style={{ padding: "5px 11px", borderRadius: 999, border: `1px solid ${on ? "var(--indigo-line)" : "var(--line-2)"}`, background: on ? "var(--cp-indigo-soft)" : "transparent",
        color: on ? "var(--cp-indigo)" : "var(--cp-ink-2)", fontSize: 12, cursor: rest.disabled ? "not-allowed" : "pointer", opacity: rest.disabled ? 0.5 : 1, ...(rest.style ?? {}) }}>
      {children}
    </button>
  );
}

/** − value + for a level; typing works too. An empty level starts from the reference price on − / +. */
function LevelRow({ label, value, onChange, step, base, testId, allowEmpty }: {
  label: string; value: number | null; onChange: (v: number | null) => void; step: number; base: number; testId: string; allowEmpty: boolean;
}) {
  const round = (v: number) => Math.round(v / step) * step;
  const bump = (d: number) => onChange(Math.max(step, Number(round((value ?? base) + d * step).toFixed(2))));
  return (
    <div className="flex items-center" style={{ gap: 6 }}>
      <span style={{ ...eyebrow, width: 90, flexShrink: 0 }}>{label}</span>
      <button type="button" aria-label={`${label} down`} data-testid={`${testId}-minus`} style={stepBtn} onClick={() => bump(-1)}>−</button>
      <input data-testid={testId} aria-label={label} type="number" inputMode="decimal" step={step} value={value ?? ""} placeholder="—"
        onChange={(e) => {
          const t = e.target.value.trim();
          if (t === "") { if (allowEmpty) onChange(null); return; }
          const n = Number(t);
          if (Number.isFinite(n) && n > 0) onChange(n);
        }}
        className="cp-num" style={{ flex: 1, minWidth: 0, height: 28, padding: "0 6px", borderRadius: 7, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 12, textAlign: "center" }} />
      <button type="button" aria-label={`${label} up`} data-testid={`${testId}-plus`} style={stepBtn} onClick={() => bump(1)}>+</button>
    </div>
  );
}

function LegRow({ leg, symbol, onFlip, onRemove, onQty }: { leg: BasketLeg; symbol: string; onFlip: () => void; onRemove: () => void; onQty: (q: number) => void }) {
  const buy = leg.side === "B";
  const unit = leg.kind === "CASH" ? "sh" : leg.qty === 1 ? "lot" : "lots";
  return (
    <div data-testid="ca-basket-leg" data-kind={leg.kind} data-side={leg.side} data-strike={leg.strike ?? ""} data-expiry={leg.expiry ?? ""} data-qty={leg.qty} data-entry={leg.entry}
      className="flex flex-col" style={{ gap: 6, padding: "9px 10px", borderTop: "1px solid var(--line-2)" }}>
      <div className="flex items-center" style={{ gap: 8 }}>
        <button type="button" data-testid="ca-basket-side" onClick={onFlip} title="Switch buy / sell"
          style={{ width: 46, flexShrink: 0, padding: "3px 0", borderRadius: 6, border: `1px solid ${buy ? "var(--mint-line)" : "var(--danger-line)"}`, background: buy ? "var(--mint-soft)" : "var(--cp-danger-soft)",
            color: buy ? "var(--mint)" : "var(--cp-danger)", cursor: "pointer", ...mono(10.5, { letterSpacing: "0.08em" }) }}>
          {buy ? "BUY" : "SELL"}
        </button>
        <span data-testid="ca-basket-leg-name" className="cp-num" style={{ flex: 1, minWidth: 0, fontSize: 12, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{legName(leg, symbol, fmtExpiry)}</span>
        <button type="button" data-testid="ca-basket-remove" aria-label="Remove leg" onClick={onRemove} style={{ border: 0, background: "none", color: "var(--cp-ink-3)", cursor: "pointer", fontSize: 15, lineHeight: 1 }}>×</button>
      </div>
      <div className="flex items-center" style={{ gap: 8 }}>
        <span data-testid="ca-basket-leg-price" title={leg.priceSource} style={{ flex: 1, minWidth: 0, fontSize: 11, color: "var(--cp-ink-3)" }}>
          {isOption(leg) ? "Premium" : "Price"} <span className="cp-num">{rs(leg.entry)}</span> · <span className="cp-num">{fmtNum(units(leg))}</span> qty
        </span>
        <button type="button" data-testid="ca-basket-qty-minus" aria-label="Fewer" style={{ ...stepBtn, width: 24, height: 24 }} onClick={() => onQty(leg.qty - 1)} disabled={leg.qty <= 1}>−</button>
        <span data-testid="ca-basket-qty" className="cp-num" style={{ minWidth: 44, textAlign: "center", fontSize: 12 }}>{fmtNum(leg.qty)} {unit}</span>
        <button type="button" data-testid="ca-basket-qty-plus" aria-label="More" style={{ ...stepBtn, width: 24, height: 24 }} onClick={() => onQty(leg.qty + 1)}>+</button>
      </div>
    </div>
  );
}

export function BasketPanel({ symbol, chain, notFno, last, planLevels, planId, onShowAnalysis, onClose, compact }: BasketPanelProps) {
  const b = useBasket();
  const legs = b.legs;
  const fut = useFnoFutures(notFno ? null : symbol);
  const futData = fut.data?.kind === "ok" ? fut.data.data : null;
  const futRows = futData?.futures ?? [];
  const fnoAsOf = chain?.asOf ?? futData?.as_of ?? null;
  const today = istToday();
  const asOf = chain?.asOf ?? istDay(last.at) ?? today;
  const step = priceStep(last.price);
  const placing = usePlaceBasket(symbol);

  // The chart's plan levels are the defaults for STOP / TARGET: written into the basket once, when it first has legs.
  const seeded = useRef<string | null>(null);
  useEffect(() => {
    if (!legs.length || seeded.current === symbol) return;
    seeded.current = symbol;
    if (planLevels && b.levels.stop == null && b.levels.target == null && (planLevels.stop != null || planLevels.target != null)) {
      b.setLevels({ stop: planLevels.stop, target: planLevels.target });
    }
  }, [legs.length, symbol, planLevels, b]);

  const request = useMemo(() => payoffRequestOf({ symbol, legs, refPrice: last.price, asOf, today, rangePct: 10, levels: b.levels }),
    [symbol, legs, last.price, asOf, today, b.levels]);
  const pay = useBasketPayoff(request);
  const answer = pay.data && !pay.isStale && request ? pay.data : null;
  const ex = answer?.valid ? answer.expiry ?? null : null;
  const routeProblems = answer && !answer.valid ? answer.problems.map((p) => p.message) : [];

  const futBuilt = futureLeg(futRows.map((f) => ({ expiry: f.expiry, close: f.close, settle: f.settle })), futData?.as_of ?? asOf, chain, notFno);
  const futLeg = legs.find((l) => l.kind === "FUT") ?? null;
  const cashL = legs.find((l) => l.kind === "CASH") ?? null;
  const futRow = futLeg ? futRows.find((f) => f.expiry === futLeg.expiry) : undefined;
  const futPrice = futRow ? (futRow.close != null && futRow.close > 0 ? futRow.close : futRow.settle) : null;
  const futMoved = futLeg != null && futPrice != null && Math.abs(futLeg.entry - futPrice) > 1e-6;

  // ── what PLACE posts (also posted by the strategy panel's PLACE) ──
  const sig = basketSignature(symbol, legs, b.levels);
  const cite = !!planId;
  const build = (now: Date): Ready => {
    if (!legs.length) return { ok: false, problems: ["The basket is empty."], notes: [] };
    if (cashOnly(legs) && cashL) {
      const entry = b.levels.cashEntry ?? cashL.entry;
      const rule = entryRuleFor(entry, last.price);
      const r = cashBodyOf({ symbol, leg: cashL, levels: b.levels, rule, planId: cite ? planId : null, now });
      const ruleNote = `Share trade, entry rule ${rule.replace("_", " ")}: ${ENTRY_RULE_SHORT[rule]} (entry ${rs(entry)} against the LAST ${rs(last.price)}).`;
      return r.ok ? { ok: true, request: { kind: "cash", body: r.body, signature: sig, rule }, notes: [ruleNote] } : { ok: false, problems: r.problems, notes: [ruleNote] };
    }
    if (routeProblems.length) return { ok: false, problems: routeProblems, notes: [] };
    if (!answer) return { ok: false, problems: [pay.errorText ?? "Reading the position delta from the payoff route…"], notes: [] };
    // A future priced off the chart is not a traded price: its source says so.
    const bodyLegs = legs.map((l) => (l.kind === "FUT" && futMoved && futPrice != null
      ? { ...l, priceSource: clip(`Entry level set on the chart, not a traded price (the ${l.expiry} future's last bhavcopy price ${rs(futPrice)}, ${futData?.as_of ?? ""})`, 200) } : l));
    const r = strategyBodyOf({ symbol, legs: bodyLegs, refPrice: last.price, last, fnoAsOf, delta: answer.pre_expiry?.greeks?.delta ?? null, levels: b.levels, planId: cite ? planId : null, now });
    return r.ok ? { ok: true, request: { kind: "strategy", body: r.body, signature: sig, legs: legs.length }, notes: r.notes } : { ok: false, problems: r.problems, notes: [] };
  };
  useRegisterPlaceBuilder(symbol, build);
  const ready = build(new Date());
  const shown = placing.answer && placing.answer.signature === sig ? placing.answer : null;

  // ── risk / reward from the payoff answer ──
  const atLevels = onlyUnderlying(legs) && (b.levels.stop != null || b.levels.target != null);
  const scen = (name: string) => ex?.scenarios.find((s) => s.name === name) ?? null;
  let lossLabel = "MAX LOSS", profitLabel = "MAX PROFIT", lossText = "—", profitText = "—", basis = "at expiry, before costs";
  let loss: number | null = null, profit: number | null = null;
  if (atLevels) {
    lossLabel = "RISK TO STOP"; profitLabel = "REWARD TO TARGET"; basis = "at the stop / target, after costs";
    loss = b.levels.stop != null ? scen(STOP_SCENARIO)?.net ?? null : null;
    profit = b.levels.target != null ? scen(TARGET_SCENARIO)?.net ?? null : null;
    lossText = b.levels.stop == null ? "no stop" : rs(loss, 0);
    profitText = b.levels.target == null ? "no target" : rs(profit, 0);
  } else if (ex) {
    loss = ex.loss_unbounded ? null : ex.max_loss;
    profit = ex.profit_unbounded ? null : ex.max_profit;
    lossText = ex.loss_unbounded ? "Unlimited" : rs(loss, 0);
    profitText = ex.profit_unbounded ? "Unlimited" : rs(profit, 0);
  }
  const rr = loss != null && profit != null && loss < 0 && profit > 0 ? `1 : ${fmtNum(profit / -loss, 2)}` : "—";
  const hasOpt = legs.some(isOption);
  const np = ex?.net_premium ?? null;
  const premiumLine = !hasOpt ? "NO OPTION PREMIUM" : np == null ? "OPTIONS NET —" : np < 0 ? `OPTIONS NET DEBIT ${rs(-np)}` : np > 0 ? `OPTIONS NET CREDIT ${rs(np)}` : "OPTIONS NET ₹0.00";

  const family = familyOf(legs);
  const presetProblem = notFno ?? (chain ? null : "Pick Current, Next or Far: the presets need one expiry's chain with prices.");

  return (
    <aside data-testid="ca-basket" aria-label="Paper trade basket" className="flex flex-col"
      style={{ width: compact ? "100%" : 292, maxWidth: "100%", boxSizing: "border-box", flexShrink: 0, minWidth: 0, background: "var(--bg-1)", border: "1px solid var(--line-2)", borderRadius: 14, padding: 18, boxShadow: "var(--shadow-card)", gap: 14 }}>
      <div className="flex items-center">
        <div style={{ ...mono(11), fontWeight: 500, letterSpacing: "0.14em", flex: 1, color: "var(--cp-ink-2)" }}>PAPER TRADE</div>
        <button type="button" data-testid="ca-basket-close" aria-label="Close the basket" onClick={onClose} style={{ border: 0, background: "none", color: "var(--cp-ink-3)", cursor: "pointer", fontSize: 18, lineHeight: 1 }}>×</button>
      </div>
      <div className="flex items-baseline" style={{ gap: 10 }}>
        <div style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.1 }}>Basket</div>
        <div data-testid="ca-basket-count" style={{ ...mono(11), color: "var(--cp-ink-3)" }}>{legs.length} leg{legs.length === 1 ? "" : "s"}</div>
      </div>

      <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
        <span style={{ ...eyebrow, marginRight: 4 }}>Add</span>
        <Pill data-testid="ca-basket-add-cash" on={!!cashL} disabled={!(last.price > 0)} title={last.price > 0 ? `Shares at the LAST ${rs(last.price)} (${last.source})` : "No LAST price to enter at."}
          onClick={() => b.toggleUnderlying(cashLeg(last, chain?.lotSize ?? null))}>＋ Cash</Pill>
        <Pill data-testid="ca-basket-add-future" on={!!futLeg} disabled={!futLeg && !futBuilt.ok} title={futLeg ? "Remove the future" : futBuilt.ok ? `${legName({ ...futBuilt.legs[0], id: "x" }, symbol, fmtExpiry)} at ${rs(futBuilt.legs[0].entry)} (${futBuilt.legs[0].priceSource})` : fut.isPending && !notFno ? "Reading the futures…" : futBuilt.why}
          onClick={() => { if (futLeg) b.toggleUnderlying(futLeg); else if (futBuilt.ok) b.toggleUnderlying(futBuilt.legs[0]); }}>＋ Future</Pill>
      </div>

      <div className="flex flex-col" style={{ gap: 6 }}>
        <span style={eyebrow}>Strategy</span>
        {notFno ? (
          <span data-testid="ca-basket-notfno" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{notFno} Cash only.</span>
        ) : (
          <div className="flex flex-wrap" style={{ gap: 6 }}>
            {PRESETS.map((p) => {
              const built = presetLegs(p, chain, notFno);
              const why = presetProblem ?? (built.ok ? null : built.why);
              return (
                <Pill key={p.key} data-testid={`ca-preset-${p.key}`} on={p.key !== "short_strangle" && family === p.key && legs.some(isOption)} disabled={!built.ok}
                  title={why ?? (p.warning ?? `${p.name}: ${built.ok ? built.legs.map((l) => `${l.side === "B" ? "B" : "S"} ${l.strike} ${l.kind}`).join(", ") : ""}`)}
                  onClick={() => { if (built.ok) b.replaceLegs(built.legs); }}>
                  {p.name}{p.warning && <span data-testid={`ca-preset-${p.key}-warning`} style={{ marginLeft: 5, color: "var(--cp-danger)", ...mono(9.5) }}>∞ loss</span>}
                </Pill>
              );
            })}
          </div>
        )}
        {!notFno && presetProblem && <span data-testid="ca-basket-preset-why" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{presetProblem}</span>}
      </div>

      {b.refused && <span data-testid="ca-basket-refused" role="alert" style={{ fontSize: 12, color: "var(--amber)" }}>{b.refused}</span>}

      {!legs.length ? (
        <div data-testid="ca-basket-empty" style={{ padding: "16px 12px", border: "1px dashed var(--line-3)", borderRadius: 8, fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)", textAlign: "center" }}>
          No legs yet. Press B or S on a strike in the option chain, or add cash or a future.
        </div>
      ) : (
        <div data-testid="ca-basket-legs" style={{ border: "1px solid var(--line-2)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ marginTop: -1 }}>
            {legs.map((l) => <LegRow key={l.id} leg={l} symbol={symbol} onFlip={() => b.flip(l.id)} onRemove={() => b.remove(l.id)} onQty={(q) => b.setQty(l.id, q)} />)}
          </div>
        </div>
      )}

      {legs.length > 0 && (
        <div data-testid="ca-basket-levels" className="flex flex-col" style={{ gap: 6 }}>
          {futLeg && <LevelRow label="FUT ENTRY" testId="ca-level-fut-entry" value={futLeg.entry} step={step} base={futLeg.entry} allowEmpty={false} onChange={(v) => { if (v != null) b.setEntry(futLeg.id, v); }} />}
          {cashL && !futLeg && (
            <LevelRow label="CASH ENTRY" testId="ca-level-cash-entry" value={b.levels.cashEntry ?? cashL.entry} step={step} base={cashL.entry} allowEmpty={false}
              onChange={(v) => { if (v != null) { b.setEntry(cashL.id, v); b.setLevels({ cashEntry: v }); } }} />
          )}
          <LevelRow label="STOP" testId="ca-level-stop" value={b.levels.stop} step={step} base={last.price} allowEmpty onChange={(v) => b.setLevels({ stop: v })} />
          <LevelRow label="TARGET" testId="ca-level-target" value={b.levels.target} step={step} base={last.price} allowEmpty onChange={(v) => b.setLevels({ target: v })} />
          <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>Stop and target are on the underlying (reference {rs(last.price)}).</span>
          {futMoved && futPrice != null && (
            <span data-testid="ca-basket-fut-moved" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--amber)" }}>
              The future&apos;s entry {rs(futLeg?.entry)} is not its last price {rs(futPrice)}: a strategy is recorded at the leg prices given, at once.
            </span>
          )}
        </div>
      )}

      {legs.length > 0 && (
        <div data-testid="ca-basket-risk" style={{ opacity: pay.isStale ? 0.6 : 1 }}>
          <div data-testid="ca-basket-premium" style={{ ...mono(10), color: "var(--cp-ink-2)" }}>{premiumLine} · P&amp;L {atLevels ? "AT THE STOP / TARGET" : "AT EXPIRY"}</div>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "8px 12px", borderTop: "1px solid var(--line-2)", marginTop: 8, paddingTop: 8 }}>
            <div className="flex flex-col" style={{ gap: 2 }}>
              <span style={eyebrow}>{lossLabel}</span>
              <span data-testid="ca-basket-loss" className="cp-num" style={{ fontSize: 15, color: "var(--cp-danger)" }}>{pay.isPending && !ex ? "…" : lossText}</span>
            </div>
            <div className="flex flex-col" style={{ gap: 2 }}>
              <span style={eyebrow}>{profitLabel}</span>
              <span data-testid="ca-basket-profit" className="cp-num" style={{ fontSize: 15, color: "var(--mint)" }}>{pay.isPending && !ex ? "…" : profitText}</span>
            </div>
            <div className="flex flex-col" style={{ gap: 2 }}>
              <span style={eyebrow}>R : R</span>
              <span data-testid="ca-basket-rr" className="cp-num" style={{ fontSize: 15 }}>{rr}</span>
            </div>
            <span style={{ fontSize: 10.5, lineHeight: 1.4, color: "var(--cp-ink-3)", alignSelf: "end" }}>Payoff route, {basis}.</span>
          </div>
          {pay.errorText && <span data-testid="ca-basket-payoff-error" role="alert" style={{ display: "block", marginTop: 6, fontSize: 11.5, color: "var(--cp-danger)" }}>{pay.errorText}</span>}
        </div>
      )}

      {legs.length > 0 && (
        <button type="button" data-testid="ca-basket-view" onClick={onShowAnalysis}
          style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--indigo-line)", background: "var(--cp-indigo-soft)", color: "var(--cp-indigo)", cursor: "pointer", ...mono(11, { letterSpacing: "0.06em" }) }}>
          VIEW LEGS, PAYOFF AND GREEKS ↓
        </button>
      )}

      <div style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        Click a B or S in the option chain to add a leg. Click the chart or drag the lines to set cash and future levels. Option and future legs are recorded at the prices shown and marked on each end-of-day bar; a share trade fills by its entry rule on end-of-day bars.
      </div>

      {legs.length > 0 && planId && (
        <span data-testid="ca-basket-plan" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>
          Cites trade plan {planId}: the route records it only at the plan&apos;s own legs and levels.
        </span>
      )}
      {legs.length > 0 && ready.notes.map((n, i) => <span key={i} data-testid="ca-basket-note" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-2)" }}>{n}</span>)}
      {legs.length > 0 && !ready.ok && ready.problems.map((p, i) => <span key={i} data-testid="ca-basket-problem" role="note" style={{ fontSize: 12, lineHeight: 1.45, color: "var(--amber)" }}>{p}</span>)}

      <button type="button" data-testid="ca-basket-place" disabled={!ready.ok || placing.pending}
        onClick={() => { const r = build(new Date()); if (r.ok) placing.place(r.request); }}
        style={{ padding: "10px 12px", borderRadius: 9, border: 0, background: "var(--mint)", color: "#06120B", cursor: ready.ok && !placing.pending ? "pointer" : "not-allowed", opacity: ready.ok && !placing.pending ? 1 : 0.5, ...mono(12, { letterSpacing: "0.06em", fontWeight: 600 }) }}>
        {placing.pending ? "PLACING…" : `PLACE PAPER BASKET · ${legs.length} LEG${legs.length === 1 ? "" : "S"}`}
      </button>
      {shown && (
        <span data-testid="ca-basket-answer" data-ok={shown.ok ? "true" : "false"} role={shown.ok ? "status" : "alert"}
          style={{ ...mono(shown.ok ? 10.5 : 11.5, { letterSpacing: shown.ok ? "0.06em" : 0, lineHeight: 1.45 }), color: shown.ok ? "var(--mint)" : "var(--cp-danger)", fontFamily: shown.ok ? "var(--mono)" : "inherit" }}>
          {shown.text}
        </span>
      )}
      <span style={{ ...mono(9.5), letterSpacing: "0.1em", color: "var(--amber)" }}>PAPER ONLY · NOTHING IS SENT TO A BROKER</span>
    </aside>
  );
}
