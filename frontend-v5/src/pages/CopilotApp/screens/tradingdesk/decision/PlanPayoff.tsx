/**
 * An options plan's profit or loss today and at expiry, as a chart and a table, in the full card (owner, 29 Oct: "we
 * need to show the payoff graph/table with today's date and expiry date").
 *
 * One request to the desk's payoff calculation (POST /api/desk/strategy/payoff through usePayoff, the Strategy Builder's
 * own) for the plan's legs and entry prices, at your lots per leg (the risk service's size when it gave one, else the
 * plan's):
 *   expiry      exact: what the position is worth when the options expire
 *   pre_expiry  the calculation's estimate for TODAY (IST): each option valued with Black-76, its volatility implied by
 *               its entry price on the chain date (backend services/strategy_plan/pre_expiry.py). Asked only from the
 *               chain date until the day before the expiry.
 * Both after charges (the desk cost card). One grid in 0.125% steps of the reference close, from −R% to +R%, where R covers
 * the strikes, the exit and the targets; the table's moves are multiples of R/4, so every row is a point the calculation
 * priced. Nothing is interpolated or recomputed here.
 *
 * The body is pinned by e2e/fixtures/contract-plan-payoff.json; backend tests/test_plan_payoff_contract.py runs that body
 * through the real calculation. A cash or futures plan has no section (its profit or loss does not change with time).
 */
import { useEffect, useState, type CSSProperties } from "react";
import { fmtDay, fmtPrice } from "../../trading/parts";
import { istDay } from "../overview-data";
import type { PayoffRequest, PayoffResponse } from "../strategy/strategy-contract";
import { niceTicks, px, rs, rsTick } from "../strategy/strategy-format";
import type { TradePlan } from "../strategy/trade-plan";
import { usePayoff } from "../strategy/usePayoff";
import type { PlanView } from "./plan-view";

export const STEP_PCT = 0.125;
const MAX_RANGE_PCT = 20;
const TODAY_COLOR = "var(--cp-indigo)";
const EXPIRY_COLOR = "var(--cp-ink)";

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };

interface PlanLeg {
  kind?: string; side?: string; lots?: number; lot_size?: number; entry_price?: number;
  expiry?: string | null; strike?: number | null; option_type?: string | null; price_source?: string | null;
}

function planLegs(tp: TradePlan): PlanLeg[] {
  const legs = (tp.instrument as { legs?: unknown }).legs;
  return Array.isArray(legs) ? (legs as PlanLeg[]) : [];
}

/** How far either side of the reference close the grid reaches, in whole percent: 1.5 × the farthest strike, exit or target, plus 1; 3 to 20. */
export function payoffRangePct(ref: number, prices: Array<number | null | undefined>): number {
  const far = Math.max(0, ...prices.filter((p): p is number => p != null && Number.isFinite(p)).map((p) => Math.abs(p / ref - 1) * 100));
  return Math.min(MAX_RANGE_PCT, Math.max(3, Math.ceil(far * 1.5) + 1));
}

/** The table's moves: −R, −3R/4 … +R (multiples of R/4, so each is a grid point). */
export const tableMoves = (range: number) => [-4, -3, -2, -1, 0, 1, 2, 3, 4].map((k) => (k * range) / 4);

export interface PlanPayoffAsk {
  request: PayoffRequest;
  rangePct: number;
  /** The first expiry among the legs. */
  expiry: string | null;
  /** Today's estimate was asked for (today is on or after the chain date and before the expiry). */
  estimate: boolean;
  lotsPerLeg: number;
  yourSize: boolean;
}

/** The calculation's request for an options plan, or null when the plan is not one the calculation can price. */
export function planPayoffRequest(tp: TradePlan, lotsPerLeg: number | null, today: string): PlanPayoffAsk | null {
  const legs = planLegs(tp);
  const ref = tp.entry.reference_close;
  if (tp.instrument.segment !== "options" || !tp.instrument.symbol || !legs.length || ref == null || !(ref > 0)) return null;
  if (legs.some((l) => l.entry_price == null || l.lot_size == null || !l.kind || !l.side)) return null;
  const expiry = legs.map((l) => l.expiry).filter((e): e is string => !!e).sort()[0] ?? null;
  const range = payoffRangePct(ref, [...legs.map((l) => l.strike), tp.stop.price, ...tp.targets.map((t) => t.price)]);
  const asOf = tp.data_as_of?.chain ?? tp.data_as_of?.fno ?? null;
  const estimate = expiry != null && today < expiry && (asOf == null || asOf <= today);
  // Your size applies when every leg has the same lots (the risk service sizes "lots per leg").
  const same = new Set(legs.map((l) => l.lots ?? 1)).size === 1;
  const yourSize = lotsPerLeg != null && lotsPerLeg >= 1 && same;
  const lots = yourSize ? (lotsPerLeg as number) : (legs[0].lots ?? 1);
  return {
    request: {
      underlying: tp.instrument.symbol,
      reference_price: ref,
      ...(asOf ? { as_of: asOf } : {}),
      legs: legs.map((l) => ({
        kind: l.kind, side: l.side, quantity: yourSize ? lots : (l.lots ?? 1), lot_size: l.lot_size, entry_price: l.entry_price,
        ...(l.expiry ? { expiry: l.expiry } : {}), ...(l.strike != null ? { strike: l.strike } : {}),
        ...(l.option_type ? { option_type: l.option_type } : {}), ...(l.price_source ? { price_source: l.price_source } : {}),
      })) as PayoffRequest["legs"],
      grid: { from_pct: -range, to_pct: range, points: Math.round((2 * range) / STEP_PCT) + 1 },
      ...(estimate ? { pre_expiry: { date: today } } : {}),
    },
    rangePct: range, expiry, estimate, lotsPerLeg: lots, yourSize,
  };
}

/** The grid index of a move, when the answer's grid has that point (else null: the cell prints "—"). */
function indexOf(grid: number[], ref: number, range: number, move: number): number | null {
  const i = Math.round((move + range) / STEP_PCT);
  const want = ref * (1 + move / 100);
  return i >= 0 && i < grid.length && Math.abs(grid[i] - want) <= Math.max(0.02, want * 1e-6) ? i : null;
}

const tone = (n: number | null | undefined) => (n == null ? undefined : n > 0 ? "var(--mint)" : n < 0 ? "var(--cp-danger)" : undefined);
const moveText = (m: number) => (m === 0 ? "now" : `${m > 0 ? "+" : "−"}${Math.abs(m).toLocaleString("en-IN", { maximumFractionDigits: 3 })}%`);

export function PlanPayoff({ v }: { v: PlanView }) {
  const a = v.accountSize;
  const lots = a && (a.status === "sized" || a.status === "not_confirmed") ? a.lots : null;
  const today = istDay(new Date().toISOString()) ?? new Date().toISOString().slice(0, 10);
  const ask = planPayoffRequest(v.plan, lots, today);
  const pay = usePayoff(ask?.request ?? null, { debounceMs: 0 });
  if (!ask) return null;
  return (
    <section data-testid="dc-sec-payoff" className="flex min-w-0 flex-col" style={{ gap: 6, paddingTop: 8, borderTop: "1px solid var(--cp-line)" }}>
      <h5 className="cp-eyebrow m-0" style={{ fontWeight: 400, fontSize: 9.5 }}>Profit or loss: today and at expiry</h5>
      <PayoffBody ask={ask} plan={v.plan} today={today} data={pay.data} errorText={pay.errorText} pending={pay.isPending} retry={pay.refetch} />
    </section>
  );
}

function PayoffBody({ ask, plan, today, data, errorText, pending, retry }: {
  ask: PlanPayoffAsk; plan: TradePlan; today: string; data: PayoffResponse | undefined; errorText: string | null; pending: boolean; retry: () => void;
}) {
  if (errorText) {
    return (
      <span data-testid="dc-payoff-error" role="alert" className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 12.5, color: "var(--amber)" }}>
        The profit or loss could not be worked out just now: {errorText}
        <button type="button" data-testid="dc-payoff-retry" className="cp-btn" data-variant="ghost" onClick={retry} style={{ padding: "3px 10px", fontSize: 12 }}>Try again</button>
      </span>
    );
  }
  if (!data) return <span data-testid="dc-payoff-pending" style={quiet}>{pending ? "Working out the profit or loss…" : "Not worked out yet."}</span>;
  if (!data.valid || !data.expiry) {
    return <span data-testid="dc-payoff-invalid" style={{ fontSize: 12.5, color: "var(--amber)" }}>The calculation did not accept this plan&rsquo;s options: {data.problems[0]?.message ?? "no reason was given"}.</span>;
  }
  const ex = data.expiry;
  const pre = data.pre_expiry && data.pre_expiry.grid && data.pre_expiry.net && data.pre_expiry.grid.length === ex.grid.length ? data.pre_expiry : null;
  const ref = plan.entry.reference_close as number;
  const sym = plan.instrument.symbol ?? "";
  const todayLabel = `Today, ${fmtDay(today)} (estimated)`;
  const expiryLabel = ask.expiry ? `At expiry, ${fmtDay(ask.expiry)}` : "At expiry";
  const noToday = ask.estimate
    ? !pre ? `No estimate for today: ${data.pre_expiry?.unavailable[0]?.reason ?? "the calculation gave none"}.` : null
    : ask.expiry == null ? "No estimate for today: the plan’s options carry no expiry date."
    : today >= ask.expiry ? `These options ${today === ask.expiry ? "expire today" : `expired on ${fmtDay(ask.expiry)}`}: only the expiry values apply.`
    : "No estimate for today: the option prices are from a later day than today.";
  const lotSize = (plan.instrument.lot_size ?? null) as number | null;
  // The day the entry prices belong to: a board plan's chain date, a Strategy Builder / Copilot plan's F&O date.
  const pricesDay = plan.data_as_of?.chain ?? plan.data_as_of?.fno ?? null;
  const marks = [
    { key: "now", price: ref, label: `${sym} now ${fmtPrice(ref)}`, color: "var(--cp-ink-2)" },
    ...(plan.stop.price != null ? [{ key: "exit", price: plan.stop.price, label: `exit if wrong ${fmtPrice(plan.stop.price)}`, color: "var(--cp-danger)" }] : []),
    ...plan.targets.filter((t) => t.price != null).map((t, i) => ({ key: `t${i + 1}`, price: t.price as number, label: `target ${i + 1} ${fmtPrice(t.price)}`, color: "var(--mint)" })),
  ];
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <span data-testid="dc-payoff-size" style={quiet}>
        After charges, for {ask.lotsPerLeg} lot{ask.lotsPerLeg === 1 ? "" : "s"} per leg{lotSize != null ? ` × ${lotSize}` : ""} ({ask.yourSize ? "your size" : "the plan’s size"}).
        {" "}Option prices of {pricesDay ? fmtDay(pricesDay) : "the plan’s day"}, end of day.
      </span>
      <div className="flex flex-wrap items-center" style={{ gap: "2px 14px", fontSize: 12 }} data-testid="dc-payoff-legend">
        {pre && (
          <span data-testid="dc-payoff-legend-today" className="flex items-center" style={{ gap: 6, color: "var(--cp-ink-2)" }}>
            <svg width="22" height="6" aria-hidden><line x1="0" y1="3" x2="22" y2="3" style={{ stroke: TODAY_COLOR }} strokeWidth={2} strokeDasharray="5 3" /></svg>{todayLabel}
          </span>
        )}
        <span data-testid="dc-payoff-legend-expiry" className="flex items-center" style={{ gap: 6, color: "var(--cp-ink-2)" }}>
          <svg width="22" height="6" aria-hidden><line x1="0" y1="3" x2="22" y2="3" style={{ stroke: EXPIRY_COLOR }} strokeWidth={2} /></svg>{expiryLabel}
        </span>
      </div>
      {noToday && <span data-testid="dc-payoff-no-today" style={{ ...quiet, color: "var(--amber)" }}>{noToday}</span>}
      <PayoffLines grid={ex.grid} expiry={ex.net} today={pre?.net ?? null} marks={marks}
        label={`Profit or loss after charges ${pre ? `${todayLabel.toLowerCase()} and ` : ""}${expiryLabel.toLowerCase()}, for ${sym} from ${fmtPrice(ex.grid[0])} to ${fmtPrice(ex.grid[ex.grid.length - 1])}. The table below lists the values.`} />
      <span data-testid="dc-payoff-marks" style={quiet}>
        {marks.map((m, i) => <span key={m.key}>{i ? " · " : ""}<span style={{ color: m.color }}>┆</span> {m.label}</span>)}
      </span>
      <div style={{ overflowX: "auto" }} data-testid="dc-payoff-table-wrap">
        <table data-testid="dc-payoff-table" className="cp-num" style={{ borderCollapse: "collapse", fontSize: 12, width: "100%" }}>
          <caption className="sr-only">Profit or loss after charges at each price of {sym}</caption>
          <thead>
            <tr style={{ color: "var(--cp-ink-3)", textAlign: "right" }}>
              <th scope="col" style={{ textAlign: "left", fontWeight: 400, padding: "3px 6px" }}>If {sym} is at</th>
              {pre && <th scope="col" data-testid="dc-payoff-col-today" style={{ fontWeight: 400, padding: "3px 6px" }}>{todayLabel}</th>}
              <th scope="col" data-testid="dc-payoff-col-expiry" style={{ fontWeight: 400, padding: "3px 6px" }}>{expiryLabel}</th>
            </tr>
          </thead>
          <tbody>
            {tableMoves(ask.rangePct).map((m) => {
              const i = indexOf(ex.grid, ref, ask.rangePct, m);
              const t = i != null && pre ? pre.net![i] : null;
              const e = i != null ? ex.net[i] : null;
              return (
                <tr key={m} data-testid="dc-payoff-row" data-move={m} style={{ borderTop: "1px solid var(--cp-line)", textAlign: "right", fontWeight: m === 0 ? 600 : 400 }}>
                  <td style={{ textAlign: "left", padding: "3px 6px" }}>
                    <span data-testid="dc-payoff-price">{i != null ? fmtPrice(ex.grid[i]) : "—"}</span>
                    {" "}<span data-testid="dc-payoff-move" style={{ color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>({moveText(m)})</span>
                  </td>
                  {pre && <td data-testid="dc-payoff-today" style={{ padding: "3px 6px", color: tone(t), whiteSpace: "nowrap" }}>{rs(t, { signed: true })}</td>}
                  <td data-testid="dc-payoff-expiry" style={{ padding: "3px 6px", color: tone(e), whiteSpace: "nowrap" }}>{rs(e, { signed: true })}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {ex.breakevens.length > 0 && (
        <span data-testid="dc-payoff-breakeven" style={quiet}>At expiry it breaks even at {ex.breakevens.map((b) => fmtPrice(b)).join(" and ")} (before charges).</span>
      )}
      {pre && (
        <span style={quiet}>
          Today&rsquo;s line is an estimate: each option is valued from the price swings its entry price implies, and real prices
          can differ. The expiry line is exact at the prices shown. An idea to review, not a recommendation.
        </span>
      )}
    </div>
  );
}

/** Width of an observed box, or null until it is measured (as ChartTab.tsx measures its chart). */
function useBoxWidth(box: HTMLElement | null): number | null {
  const [w, setW] = useState<number | null>(null);
  useEffect(() => {
    if (!box || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const v = entries[0]?.contentRect.width;
      if (v) setW(v);
    });
    ro.observe(box);
    return () => ro.disconnect();
  }, [box]);
  return w;
}

/** The two lines on one price axis, the zero line and the marked prices. Inline SVG, the house style; drawn at its real
 *  width (one viewBox unit = one pixel), so the axis text stays legible on a phone and on a wide screen. */
function PayoffLines({ grid, expiry, today, marks, label }: {
  grid: number[]; expiry: number[]; today: number[] | null; marks: Array<{ key: string; price: number; color: string }>; label: string;
}) {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const measured = useBoxWidth(box);
  const W = Math.round(Math.min(900, Math.max(260, measured ?? 540)));
  const H = W < 420 ? 180 : 210, L = 52, R = 8, T = 8, B = 22;
  if (grid.length < 2 || expiry.length !== grid.length) return null;
  const all = [...expiry, ...(today ?? []), 0];
  const pad = (Math.max(...all) - Math.min(...all) || 1) * 0.08;
  const lo = Math.min(...all) - pad, hi = Math.max(...all) + pad;
  const x0 = grid[0], x1 = grid[grid.length - 1];
  const xOf = (p: number) => L + ((p - x0) / (x1 - x0 || 1)) * (W - L - R);
  const yOf = (n: number) => T + ((hi - n) / (hi - lo || 1)) * (H - T - B);
  const path = (ys: number[]) => ys.map((y, i) => `${i ? "L" : "M"}${xOf(grid[i]).toFixed(1)},${yOf(y).toFixed(1)}`).join("");
  return (
    <div ref={setBox} className="min-w-0">
    <svg data-testid="dc-payoff-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ width: "100%", height: "auto", display: "block" }}>
      {niceTicks(lo, hi, 5).map((y) => (
        <g key={`y${y}`}>
          <line x1={L} x2={W - R} y1={yOf(y)} y2={yOf(y)} style={{ stroke: "var(--cp-line)" }} strokeWidth={0.6} />
          <text x={L - 6} y={yOf(y) + 3} textAnchor="end" className="cp-num" style={{ fontSize: 10, fill: "var(--cp-ink-3)" }}>{rsTick(y)}</text>
        </g>
      ))}
      {niceTicks(x0, x1, W < 420 ? 3 : 5).map((x) => (
        <text key={`x${x}`} x={xOf(x)} y={H - 6} textAnchor="middle" className="cp-num" style={{ fontSize: 10, fill: "var(--cp-ink-3)" }}>{px(x)}</text>
      ))}
      <line x1={L} x2={W - R} y1={yOf(0)} y2={yOf(0)} style={{ stroke: "var(--cp-ink-3)" }} strokeWidth={1} />
      {marks.filter((m) => m.price >= x0 && m.price <= x1).map((m) => (
        <line key={m.key} data-testid={`dc-payoff-mark-${m.key}`} x1={xOf(m.price)} x2={xOf(m.price)} y1={T} y2={H - B} style={{ stroke: m.color }} strokeWidth={1} strokeDasharray="3 3" />
      ))}
      <path data-testid="dc-payoff-line-expiry" d={path(expiry)} fill="none" style={{ stroke: EXPIRY_COLOR }} strokeWidth={1.8} strokeLinejoin="round" />
      {today && <path data-testid="dc-payoff-line-today" d={path(today)} fill="none" style={{ stroke: TODAY_COLOR }} strokeWidth={1.8} strokeDasharray="6 4" strokeLinejoin="round" />}
    </svg>
    </div>
  );
}
