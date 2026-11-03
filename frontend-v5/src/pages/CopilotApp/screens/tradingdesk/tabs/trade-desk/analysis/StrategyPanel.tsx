/**
 * Chart Analysis v2 — the strategy panel under the chart (the design's "Strategy" card; test_reports/chart_analysis_v2_TESTCASES.md
 * U7, U8, U11). Shown only while the basket has legs.
 *
 *   legs table        the basket's legs; IV = the chain's end-of-day model IV for the contract; LTP = the live Kite quote while
 *                     the feed says the session is live (POST /api/live/fno-quotes), else the end-of-day close (EOD);
 *                     Delta / Gamma / Theta / Vega = the payoff route's position Greeks per leg (pre_expiry.per_leg_greeks),
 *                     POSITION TOTAL = pre_expiry.greeks
 *   margin            POST /api/fno/margin (Zerodha's calculator through the platform Kite session); hedge benefit = the route's hedge_benefit
 *                     is sent by the route, so it is "—" with why
 *   P&L payoff        POST /api/desk/strategy/payoff over ±5 / 10 / 15 %: at expiry and today (pre_expiry), breakevens,
 *                     max loss / profit; the scenario table at the 11 scenario prices (BE-3 pre_expiry.scenarios for today's
 *                     P&L and Greeks; without it the Greek cells are "—" and today's P&L is the today curve at that price)
 *
 * Nothing is priced here: every figure is a route's. Paper only.
 */
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { fmtNum } from "../../../../../components/ui";
import { useLiveMeta } from "../../../../../lib/useLiveQuotes";
import { useFnoFutures } from "../../../../trading/fno";
import { fmtDay } from "../../../../trading/parts";
import type { Greeks } from "../../../strategy/strategy-contract";
import { useBasket, type BasketLeg } from "./basket";
import type { AnalysisChain } from "./chain-data";
import { RANGES, fmtExpiry, istToday, marginBodyOf, payoffRequestOf, scenarioName, scenarioPcts, type RangePct } from "./presets";
import { todayScenarios, useBasketLive, useBasketMargin, useBasketPayoff, usePlaceBasket, usePlaceBuilder } from "./basket-routes";

export interface StrategyPanelProps {
  symbol: string;
  chain: AnalysisChain | null;
  refPrice: number;
  refAsOf: string;
  compact: boolean;
}

const mono = (size: number, extra: CSSProperties = {}): CSSProperties => ({ fontFamily: "var(--mono)", fontSize: size, ...extra });
const head: CSSProperties = { ...mono(9.5), letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" };
const rs = (n: number | null | undefined, digits = 0, signed = false) =>
  (n == null || !Number.isFinite(n) ? "—" : `${n < 0 ? "−" : signed && n > 0 ? "+" : ""}₹${fmtNum(Math.abs(n), digits)}`);
const g = (n: number | null | undefined, digits: number) => (n == null || !Number.isFinite(n) ? "—" : `${n < 0 ? "−" : ""}${fmtNum(Math.abs(n), digits)}`);
const tone = (n: number | null | undefined) => (n == null || !Number.isFinite(n) || n === 0 ? "var(--cp-ink-2)" : n > 0 ? "var(--mint)" : "var(--cp-danger)");
const RIGHT: Record<BasketLeg["kind"], string> = { CE: "CALL", PE: "PUT", FUT: "FUTURE", CASH: "EQUITY" };
// Every row is its own grid, so no column may size to its content: a fixed minimum keeps header and legs aligned.
const COLS = "54px minmax(96px, 1.3fr) 62px 62px 96px 92px 66px 66px 60px 66px 66px 66px 66px 28px";
const smallBtn: CSSProperties = { width: 22, height: 22, borderRadius: 6, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", cursor: "pointer", ...mono(12), padding: 0 };

/** Calendar days from `from` to `to` (YYYY-MM-DD). */
const daysBetween = (from: string, to: string) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);

/** Round axis ticks covering [min, max]. */
function ticks(min: number, max: number, count: number): number[] {
  const span = max - min || Math.abs(max) || 1;
  const rough = span / Math.max(1, count - 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) out.push(Number(v.toFixed(6)));
  return out;
}
const tick = (n: number) => {
  const a = Math.abs(n);
  const s = n < 0 ? "−" : "";
  if (a >= 1_00_000) return `${s}₹${+(a / 1_00_000).toFixed(2)}L`;
  if (a >= 1_000) return `${s}₹${+(a / 1_000).toFixed(1)}k`;
  return `${s}₹${+a.toFixed(0)}`;
};

function Cell({ children, style, testId, title }: { children: ReactNode; style?: CSSProperties; testId?: string; title?: string }) {
  return <span data-testid={testId} title={title} className="cp-num" style={{ fontSize: 12, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", ...style }}>{children}</span>;
}

/** The P&L payoff chart: what the route answered, drawn (gross, the basis of its max profit / loss and breakevens). */
function PayoffSvg({ grid, expiry, todayGrid, today, breakevens, spot }: {
  grid: number[]; expiry: number[]; todayGrid: number[] | null; today: number[] | null; breakevens: number[]; spot: number;
}) {
  const W = 760, H = 250, L = 64, R = 14, T = 14, B = 28;
  const all = [...expiry, ...(today ?? []), 0].filter((v) => Number.isFinite(v));
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08;
  lo -= pad; hi += pad;
  const x0 = grid[0], x1 = grid[grid.length - 1];
  const X = (p: number) => L + ((p - x0) / (x1 - x0 || 1)) * (W - L - R);
  const Y = (v: number) => T + ((hi - v) / (hi - lo || 1)) * (H - T - B);
  const y0 = Y(0);
  const pts = (xs: number[], ys: number[]) => xs.map((p, i) => `${X(p).toFixed(1)},${Y(ys[i]).toFixed(1)}`).join(" ");
  const area = `${X(x0).toFixed(1)},${y0.toFixed(1)} ${pts(grid, expiry)} ${X(x1).toFixed(1)},${y0.toFixed(1)}`;
  const yt = ticks(lo, hi, 5);
  const xt = ticks(x0, x1, 6).filter((p) => p >= x0 && p <= x1);
  const id = "ca-payoff-clip";
  return (
    <svg data-testid="ca-payoff-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Profit and loss against the underlying price, at expiry and today" style={{ display: "block", width: "100%", height: "auto" }}>
      <defs>
        <clipPath id={`${id}-up`}><rect x={0} y={0} width={W} height={Math.max(0, y0)} /></clipPath>
        <clipPath id={`${id}-down`}><rect x={0} y={y0} width={W} height={Math.max(0, H - y0)} /></clipPath>
      </defs>
      {yt.map((v) => (
        <g key={`y${v}`}>
          <line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} style={{ stroke: "var(--cp-line)" }} strokeWidth={1} />
          <text x={L - 6} y={Y(v) + 3} textAnchor="end" style={{ fill: "var(--cp-ink-3)", fontFamily: "var(--mono)", fontSize: 9.5 }}>{tick(v)}</text>
        </g>
      ))}
      {xt.map((p) => <text key={`x${p}`} x={X(p)} y={H - 8} textAnchor="middle" style={{ fill: "var(--cp-ink-3)", fontFamily: "var(--mono)", fontSize: 9.5 }}>{fmtNum(p)}</text>)}
      <polygon data-testid="ca-payoff-profit" points={area} clipPath={`url(#${id}-up)`} style={{ fill: "var(--mint-soft)" }} />
      <polygon data-testid="ca-payoff-loss" points={area} clipPath={`url(#${id}-down)`} style={{ fill: "var(--danger-soft)" }} />
      <line data-testid="ca-payoff-zero" x1={L} x2={W - R} y1={y0} y2={y0} style={{ stroke: "var(--line-3)" }} strokeWidth={1} />
      {spot >= x0 && spot <= x1 && (
        <g data-testid="ca-payoff-spot" data-value={spot}>
          <line x1={X(spot)} x2={X(spot)} y1={T} y2={H - B} style={{ stroke: "var(--cp-ink-3)" }} strokeDasharray="3 3" strokeWidth={1} />
          <text x={X(spot) + 4} y={T + 9} style={{ fill: "var(--cp-ink-3)", fontFamily: "var(--mono)", fontSize: 9.5 }}>SPOT {fmtNum(spot, 1)}</text>
        </g>
      )}
      {todayGrid && today && <polyline data-testid="ca-payoff-today" points={pts(todayGrid, today)} fill="none" style={{ stroke: "var(--cp-indigo)" }} strokeWidth={1.8} strokeDasharray="5 4" />}
      <polyline data-testid="ca-payoff-expiry" points={pts(grid, expiry)} fill="none" style={{ stroke: "var(--cp-ink)" }} strokeWidth={1.8} strokeLinejoin="round" />
      {breakevens.filter((p) => p >= x0 && p <= x1).map((p) => (
        <g key={`be${p}`} data-testid="ca-payoff-be" data-value={p}>
          <circle cx={X(p)} cy={y0} r={4} style={{ fill: "var(--amber)" }} />
          <text x={X(p)} y={y0 - 8} textAnchor="middle" style={{ fill: "var(--amber)", fontFamily: "var(--mono)", fontSize: 9.5 }}>BE {fmtNum(p, 1)}</text>
        </g>
      ))}
    </svg>
  );
}

export function StrategyPanel({ symbol, chain, refPrice, refAsOf, compact }: StrategyPanelProps) {
  const b = useBasket();
  const legs = b.legs;
  const [range, setRange] = useState<RangePct>(10);
  const today = istToday();
  const request = useMemo(() => payoffRequestOf({ symbol, legs, refPrice, asOf: refAsOf, today, rangePct: range, levels: b.levels }),
    [symbol, legs, refPrice, refAsOf, today, range, b.levels]);
  const pay = useBasketPayoff(request);
  const marginBody = useMemo(() => marginBodyOf(symbol, legs), [symbol, legs]);
  const margin = useBasketMargin(marginBody);
  const meta = useLiveMeta();
  const live = useBasketLive(symbol, legs, meta.mode === "live");
  const fut = useFnoFutures(legs.some((l) => l.kind === "FUT") ? symbol : null);
  const placing = usePlaceBasket(symbol);
  const builder = usePlaceBuilder(symbol);
  if (!legs.length) return null;

  const data = pay.data && request ? pay.data : null;
  const fresh = !!data && !pay.isStale;
  const ex = data?.valid ? data.expiry ?? null : null;
  const pre = data?.valid ? data.pre_expiry ?? null : null;
  const scenToday = fresh ? todayScenarios(data ?? undefined) : null;
  const expiries = legs.map((l) => l.expiry).filter((e): e is string => !!e).sort();
  const expiry = expiries[0] ?? null;
  const dte = expiry ? daysBetween(today, expiry) : null;
  const futRows = fut.data?.kind === "ok" ? fut.data.data.futures : [];

  const rowOf = (l: BasketLeg) => (chain && chain.expiry === l.expiry ? chain.rows.find((r) => r.strike === l.strike) ?? null : null);
  const sideOf = (l: BasketLeg) => { const r = rowOf(l); return l.kind === "CE" ? r?.call ?? null : l.kind === "PE" ? r?.put ?? null : null; };
  const ltpOf = (l: BasketLeg, i: number): { v: number | null; src: string } => {
    const at = live.at[i];
    const q = at != null ? live.answer?.quotes[String(at)] : undefined;
    if (live.answer?.available && q) return { v: q.last_price, src: "Kite live quote" };
    if (l.kind === "CASH") return { v: refPrice, src: "the underlying's LAST" };
    if (l.kind === "FUT") {
      const f = futRows.find((x) => x.expiry === l.expiry);
      return { v: f?.close ?? f?.settle ?? null, src: f ? `EOD ${f.close != null ? "close" : "settle"}, ${fut.data?.kind === "ok" ? fut.data.data.as_of : ""}` : "not in the futures read" };
    }
    const s = sideOf(l);
    return { v: s?.close ?? null, src: s ? `EOD close, ${chain?.asOf}` : "not in the chain shown (pick its expiry)" };
  };
  const greeksOf = (i: number): Greeks | null => (fresh ? pre?.per_leg_greeks.find((x) => x.leg === i)?.greeks ?? null : null);
  const total = fresh ? pre?.greeks ?? null : null;
  const why = !data ? null : !data.valid ? data.problems.map((p) => p.message).join(" ") : pre?.unavailable.length ? pre.unavailable.map((u) => `Leg ${u.leg + 1}: ${u.reason}`).join(" ") : !pre ? "The route sent no today curve or Greeks." : null;

  const ready = builder ? builder(new Date()) : null;
  const sig = ready?.ok ? ready.request.signature : null;
  const shown = placing.answer && (sig == null || placing.answer.signature === sig) ? placing.answer : null;

  const m = margin.data;
  const pcts = scenarioPcts(range);
  const preGrid = pre?.grid ?? null;
  const preGross = pre?.gross ?? null;
  const todayAt = (price: number, name: string): number | null => {
    const s = scenToday?.find((x) => x.name === name);
    if (s) return s.gross;
    if (!fresh || !preGrid || !preGross) return null;
    const k = preGrid.findIndex((p) => Math.abs(p - price) < 0.011);
    return k >= 0 ? preGross[k] : null;
  };

  return (
    <section id="ca-strategy-panel" data-testid="ca-strategy" className="flex min-w-0 flex-col"
      style={{ gap: 16, padding: compact ? 16 : 22, borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line-2)", boxShadow: "var(--shadow-card)" }}>
      <div className="flex flex-wrap items-baseline" style={{ gap: "4px 14px" }}>
        <div style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1.1 }}>Strategy</div>
        <span data-testid="ca-strategy-meta" style={{ ...mono(11), color: "var(--cp-ink-3)" }}>
          {legs.length} LEG{legs.length === 1 ? "" : "S"} · {expiry ? `EXPIRY ${fmtDay(expiry).toUpperCase()} · ${dte} DAY${dte === 1 ? "" : "S"}` : "NO EXPIRY (CASH)"}
        </span>
      </div>

      <div data-testid="ca-strategy-legs-box" style={{ overflowX: "auto", maxWidth: "100%", border: "1px solid var(--line-2)", borderRadius: 10 }}>
        <div style={{ minWidth: 1050, opacity: pay.isStale ? 0.7 : 1 }}>
          <div data-testid="ca-strategy-head" className="grid items-center" style={{ gridTemplateColumns: COLS, gap: 6, padding: "8px 12px", ...head }}>
            {["Action", "Underlying", "Strike", "Right", "Expiry", "Lots", "Entry", "LTP", "IV", "Delta", "Gamma", "Theta", "Vega", ""].map((h, i) => <span key={i} style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h}</span>)}
          </div>
          {legs.map((l, i) => {
            const gk = greeksOf(i);
            const ltp = ltpOf(l, i);
            const iv = sideOf(l)?.iv ?? null;
            const buy = l.side === "B";
            return (
              <div key={l.id} data-testid="ca-strategy-leg" data-kind={l.kind} data-index={i} className="grid items-center" style={{ gridTemplateColumns: COLS, gap: 6, padding: "7px 12px", borderTop: "1px solid var(--cp-line)" }}>
                <button type="button" data-testid="ca-strategy-side" onClick={() => b.flip(l.id)} title="Switch buy / sell"
                  style={{ ...mono(10.5, { letterSpacing: "0.06em" }), padding: "2px 0", borderRadius: 5, border: 0, background: buy ? "var(--mint-soft)" : "var(--cp-danger-soft)", color: buy ? "var(--mint)" : "var(--cp-danger)", cursor: "pointer" }}>
                  {buy ? "BUY" : "SELL"}
                </button>
                <Cell>{symbol}</Cell>
                <Cell testId="ca-strategy-strike">{l.strike != null ? fmtNum(l.strike, l.strike % 1 ? 1 : 0) : "—"}</Cell>
                <Cell style={{ ...mono(10.5), letterSpacing: "0.06em" }}>{RIGHT[l.kind]}</Cell>
                <Cell>{l.expiry ? fmtExpiry(l.expiry) : "—"}</Cell>
                <span className="flex items-center" style={{ gap: 4 }}>
                  <button type="button" data-testid="ca-strategy-qty-minus" aria-label="Fewer" style={smallBtn} disabled={l.qty <= 1} onClick={() => b.setQty(l.id, l.qty - 1)}>−</button>
                  <Cell testId="ca-strategy-qty" style={{ minWidth: 24, textAlign: "center" }} title={l.kind === "CASH" ? "shares" : `lots of ${l.lotSize}`}>{fmtNum(l.qty)}</Cell>
                  <button type="button" data-testid="ca-strategy-qty-plus" aria-label="More" style={smallBtn} onClick={() => b.setQty(l.id, l.qty + 1)}>+</button>
                </span>
                <Cell testId="ca-strategy-entry" title={l.priceSource}>{fmtNum(l.entry, 2)}</Cell>
                <Cell testId="ca-strategy-ltp" title={ltp.src}>{ltp.v == null ? "—" : fmtNum(ltp.v, 2)}</Cell>
                <Cell testId="ca-strategy-iv" style={{ color: "var(--cp-indigo)" }} title={iv != null ? `Chain model IV, end of day ${chain?.asOf}` : l.kind === "CE" || l.kind === "PE" ? "Not in the chain shown" : "No IV for a future or shares"}>{iv == null ? "—" : `${fmtNum(iv, 1)}%`}</Cell>
                <Cell testId="ca-strategy-delta">{fresh ? g(gk?.delta, 2) : "…"}</Cell>
                <Cell testId="ca-strategy-gamma">{fresh ? g(gk?.gamma, 4) : "…"}</Cell>
                <Cell testId="ca-strategy-theta" style={{ color: "var(--amber)" }}>{fresh ? g(gk?.theta, 2) : "…"}</Cell>
                <Cell testId="ca-strategy-vega">{fresh ? g(gk?.vega, 2) : "…"}</Cell>
                <button type="button" data-testid="ca-strategy-remove" aria-label="Remove leg" onClick={() => b.remove(l.id)} style={{ border: 0, background: "none", color: "var(--cp-ink-3)", cursor: "pointer", fontSize: 15 }}>×</button>
              </div>
            );
          })}
          <div data-testid="ca-strategy-total" className="grid items-center" style={{ gridTemplateColumns: COLS, gap: 6, padding: "8px 12px", background: "var(--cp-line)" }}>
            <span style={{ ...head, gridColumn: "1 / span 9" }}>Position total</span>
            <Cell testId="ca-total-delta">{g(total?.delta, 2)}</Cell>
            <Cell testId="ca-total-gamma">{g(total?.gamma, 4)}</Cell>
            <Cell testId="ca-total-theta" style={{ color: "var(--amber)" }}>{g(total?.theta, 2)}</Cell>
            <Cell testId="ca-total-vega">{g(total?.vega, 2)}</Cell>
            <span />
          </div>
        </div>
      </div>
      {why && <span data-testid="ca-strategy-why" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{why}</span>}

      <div className="flex flex-wrap items-center" style={{ gap: "10px 18px" }}>
        <span className="flex items-baseline" style={{ gap: 8 }}>
          <span style={head}>Est. margin required</span>
          <b data-testid="ca-margin-required" className="cp-num" style={{ fontSize: 15 }}>
            {!marginBody ? "—" : m?.kind === "ok" ? rs(m.required) : m?.kind === "unavailable" ? "—" : "…"}
          </b>
        </span>
        <span className="flex items-baseline" style={{ gap: 8 }}>
          <span style={head}>Hedge benefit</span>
          <b data-testid="ca-margin-benefit" className="cp-num" style={{ fontSize: 15, color: "var(--mint)" }}
            title={m?.kind === "ok" ? m.hedgeBasis ?? undefined : undefined}>
            {!marginBody ? "—" : m?.kind === "ok" ? rs(m.hedge) : m?.kind === "unavailable" ? "—" : "…"}
          </b>
        </span>
        <span style={{ flex: 1 }} />
        <button type="button" data-testid="ca-strategy-reset" onClick={() => b.reset()} className="cp-btn" data-variant="ghost" style={{ padding: "7px 12px", ...mono(11, { letterSpacing: "0.08em" }) }}>RESET</button>
        <button type="button" data-testid="ca-strategy-place" disabled={!ready?.ok || placing.pending}
          title={!builder ? "Open the basket (＋ PAPER TRADE) to place: its stop, target and plan are set there." : ready && !ready.ok ? ready.problems.join(" ") : undefined}
          onClick={() => { const r = builder?.(new Date()); if (r?.ok) placing.place(r.request); }}
          style={{ padding: "8px 14px", borderRadius: 9, border: 0, background: "var(--mint)", color: "#06120B", cursor: ready?.ok && !placing.pending ? "pointer" : "not-allowed", opacity: ready?.ok && !placing.pending ? 1 : 0.5, ...mono(11.5, { letterSpacing: "0.06em", fontWeight: 600 }) }}>
          {placing.pending ? "PLACING…" : "PLACE PAPER BASKET"}
        </button>
      </div>
      <span data-testid="ca-margin-note" style={{ fontSize: 11.5, lineHeight: 1.5, color: m?.kind === "unavailable" ? "var(--amber)" : "var(--cp-ink-3)" }}>
        {!marginBody ? "Shares have no F&O margin; the calculator prices option and future legs only."
          : m?.kind === "ok" ? `Zerodha's margin calculator (Kite), the basket's margin with the spread benefit applied${m.asOf ? `, ${m.asOf}` : ""}. ${m.hedge != null ? ` Hedge benefit: ${m.hedgeBasis ?? "the legs' margins one at a time less the basket's"}${m.standalone != null ? ` (${rs(m.standalone)} leg by leg)` : ""}.` : " The hedge benefit could not be worked out: a leg alone was not priced."}`
          : m?.kind === "unavailable" ? m.reason
          : "Asking Zerodha's margin calculator…"}
      </span>
      {!builder && <span data-testid="ca-strategy-place-why" style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>Open the basket (＋ PAPER TRADE) to place: its stop, target and plan are set there.</span>}
      {builder && ready && !ready.ok && <span data-testid="ca-strategy-problem" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--amber)" }}>{ready.problems.join(" ")}</span>}
      {shown && <span data-testid="ca-strategy-answer" data-ok={shown.ok ? "true" : "false"} role={shown.ok ? "status" : "alert"} style={{ fontSize: 12, lineHeight: 1.45, color: shown.ok ? "var(--mint)" : "var(--cp-danger)" }}>{shown.text}</span>}

      <div className="flex flex-wrap items-center" style={{ gap: "8px 14px", borderTop: "1px solid var(--line-2)", paddingTop: 14 }}>
        <div style={{ fontFamily: "var(--display)", fontSize: 22, flex: 1, minWidth: 160 }}>P&amp;L payoff</div>
        <span style={head}>Range</span>
        <div className="flex flex-wrap" style={{ gap: 6 }}>
          {RANGES.map((r) => (
            <button key={r} type="button" data-testid={`ca-range-${r}`} aria-pressed={range === r} onClick={() => setRange(r)}
              style={{ padding: "4px 10px", borderRadius: 999, border: `1px solid ${range === r ? "var(--indigo-line)" : "var(--line-2)"}`, background: range === r ? "var(--cp-indigo-soft)" : "transparent", color: range === r ? "var(--cp-indigo)" : "var(--cp-ink-2)", cursor: "pointer", ...mono(10.5) }}>
              −{r}% TO +{r}%
            </button>
          ))}
        </div>
      </div>

      <div data-testid="ca-payoff-legend" className="flex flex-wrap items-center" style={{ gap: "6px 14px", ...mono(10), color: "var(--cp-ink-3)" }}>
        <span><span style={{ color: "var(--cp-ink)" }}>━</span> AT EXPIRY</span>
        <span><span style={{ color: "var(--cp-indigo)" }}>┅</span> TODAY{pre?.date ? ` · ${fmtDay(pre.date).toUpperCase()}` : ""}</span>
        <span data-testid="ca-payoff-maxloss" style={{ color: "var(--cp-danger)" }}>MAX LOSS {ex ? (ex.loss_unbounded ? "Unlimited" : rs(ex.max_loss)) : "—"}</span>
        <span data-testid="ca-payoff-maxprofit" style={{ color: "var(--mint)" }}>MAX PROFIT {ex ? (ex.profit_unbounded ? "Unlimited" : rs(ex.max_profit)) : "—"}</span>
        <span data-testid="ca-payoff-breakeven" style={{ color: "var(--amber)" }}>BREAKEVEN {ex && ex.breakevens.length ? ex.breakevens.map((x) => fmtNum(x, 1)).join(" · ") : "—"}</span>
      </div>

      <div style={{ opacity: pay.isStale ? 0.6 : 1 }}>
        {ex ? (
          <PayoffSvg grid={ex.grid} expiry={ex.gross} todayGrid={pre?.grid ?? null} today={pre?.gross ?? null} breakevens={ex.breakevens} spot={refPrice} />
        ) : (
          <div data-testid="ca-payoff-empty" style={{ padding: "28px 12px", textAlign: "center", fontSize: 12.5, color: pay.errorText || (data && !data.valid) ? "var(--cp-danger)" : "var(--cp-ink-3)", border: "1px dashed var(--line-2)", borderRadius: 10 }}>
            {pay.errorText ?? (data && !data.valid ? `The payoff route refused this basket: ${data.problems.map((p) => p.message).join(" ")}` : "Asking the payoff route…")}
          </div>
        )}
      </div>

      <div data-testid="ca-scenario-box" style={{ overflowX: "auto", maxWidth: "100%", border: "1px solid var(--line-2)", borderRadius: 10 }}>
        <div style={{ minWidth: 860, opacity: pay.isStale ? 0.6 : 1 }}>
          {([
            ["", (p: number) => <span style={{ ...head, color: p === 0 ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>{p > 0 ? "+" : p < 0 ? "−" : ""}{fmtNum(Math.abs(p), Math.abs(p) % 1 ? 1 : 0)}%</span>, "head"],
            ["Underlying", (_p: number, name: string) => { const s = ex?.scenarios.find((x) => x.name === name); return <Cell>{s ? fmtNum(s.underlying_price, 1) : "—"}</Cell>; }, "underlying"],
            ["Payoff · expiry", (_p: number, name: string) => { const v = ex?.scenarios.find((x) => x.name === name)?.gross ?? null; return <Cell style={{ color: tone(v) }}>{rs(v, 0, true)}</Cell>; }, "expiry"],
            ["P&L · today", (_p: number, name: string) => { const s = ex?.scenarios.find((x) => x.name === name); const v = s ? todayAt(s.underlying_price, name) : null; return <Cell style={{ color: tone(v) }}>{rs(v, 0, true)}</Cell>; }, "today"],
            ["Delta", (_p: number, name: string) => <Cell>{g(scenToday?.find((x) => x.name === name)?.greeks?.delta, 2)}</Cell>, "delta"],
            ["Gamma", (_p: number, name: string) => <Cell>{g(scenToday?.find((x) => x.name === name)?.greeks?.gamma, 4)}</Cell>, "gamma"],
            ["Theta", (_p: number, name: string) => <Cell style={{ color: "var(--amber)" }}>{g(scenToday?.find((x) => x.name === name)?.greeks?.theta, 2)}</Cell>, "theta"],
            ["Vega", (_p: number, name: string) => <Cell>{g(scenToday?.find((x) => x.name === name)?.greeks?.vega, 2)}</Cell>, "vega"],
          ] as Array<[string, (p: number, name: string) => ReactNode, string]>).map(([label, render, key]) => (
            <div key={key} data-testid={`ca-scenario-${key}`} className="grid items-center" style={{ gridTemplateColumns: "150px repeat(11, 1fr)", borderTop: key === "head" ? 0 : "1px solid var(--cp-line)" }}>
              <span style={{ ...head, padding: "7px 12px" }}>{label}</span>
              {pcts.map((p) => (
                <span key={p} data-testid={`ca-scenario-${key}-cell`} data-pct={p} style={{ padding: "7px 6px", background: p === 0 ? "var(--cp-line)" : undefined, minWidth: 0 }}>{render(p, scenarioName(p))}</span>
              ))}
            </div>
          ))}
        </div>
      </div>
      {fresh && pre && !scenToday && (
        <span data-testid="ca-scenario-no-greeks" style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>
          The payoff route does not send Greeks at the scenario prices yet, so those cells are “—”; today&apos;s P&amp;L there is the today curve at the same price.
        </span>
      )}

      <p data-testid="ca-strategy-note" className="m-0" style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        P&amp;L, Greeks, breakevens and max profit / loss come from the payoff route (Black-76 for the today curve and the Greeks, each option&apos;s volatility
        solved from its entry premium on {refAsOf}; reference {rs(refPrice, 2)}). P&amp;L is before costs. Greeks are for the whole position: delta in shares per ₹1,
        gamma per ₹1, theta in ₹ per day, vega in ₹ per volatility point. IV is the chain&apos;s end-of-day model IV; LTP is the live Kite quote in the session, else the end-of-day close.
        Margin is Zerodha&apos;s calculator through the platform&apos;s Kite login, not an exchange figure. Paper only: nothing is sent to a broker.
      </p>
    </section>
  );
}
