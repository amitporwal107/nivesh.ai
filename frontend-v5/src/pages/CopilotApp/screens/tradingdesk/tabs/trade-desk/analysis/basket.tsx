/**
 * Chart Analysis v2 — the paper basket every part of the screen writes to (test_reports/chart_analysis_v2_TESTCASES.md).
 *
 *   the chart        click on the price pane sets the future's (else cash's) entry; drag STOP / TGT lines (setLevels)
 *   option chain     B / S on a strike (toggleOption)
 *   strategy cards   ADD TO BASKET (replaceLegs)
 *   basket panel     ADD Cash / Future, presets, lots, side, remove, levels, PLACE
 *   strategy panel   lots, remove, RESET
 *
 * The basket holds what the user picked and the price each leg was picked at (with where that price came from); it works
 * out no payoff, Greek, margin or P&L figure (the payoff and margin routes do). The paper engine's rules are not
 * re-implemented here beyond the leg count: a structure it refuses (unbounded loss, a short future, a short cash leg) is
 * refused by POST /api/desk/paper-trades and the panel shows the route's answer.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export type BasketLegKind = "CE" | "PE" | "FUT" | "CASH";
export type BasketSide = "B" | "S";

export interface BasketLeg {
  id: string;
  kind: BasketLegKind;
  side: BasketSide;
  /** Lots for FUT / CE / PE; shares for CASH. */
  qty: number;
  /** Option strike; null for FUT / CASH. */
  strike: number | null;
  /** YYYY-MM-DD; null for CASH. */
  expiry: string | null;
  /** Per unit: the option premium, the future's price or the share price. */
  entry: number;
  /** Where `entry` came from, e.g. "NSE F&O bhavcopy close, 2026-10-28" (the paper route requires it). */
  priceSource: string;
  /** The contract multiplier; 1 for CASH. */
  lotSize: number;
}

/** The paper engine's leg limit (backend services/strategy_limits.MAX_STRATEGY_LEGS). */
export const MAX_LEGS = 4;

export type NewLeg = Omit<BasketLeg, "id">;

export interface BasketLevels {
  /** The underlying level that invalidates the plan (stop_underlying). */
  stop: number | null;
  /** The underlying level that fulfils it (target_underlying). */
  target: number | null;
  /** The cash leg's entry level when the basket is cash only (the share trade's entry). */
  cashEntry: number | null;
}

export interface Basket {
  legs: BasketLeg[];
  levels: BasketLevels;
  /** The right-hand panel is open. */
  open: boolean;
  /** Why the last change was refused (e.g. a fifth leg), or null. */
  refused: string | null;
  setOpen: (open: boolean) => void;
  /** B / S on a chain contract: same contract + same side removes it, the other side switches it, else adds it. */
  toggleOption: (leg: NewLeg) => void;
  /** ADD Cash / Future: adds the leg, or removes the basket's leg of that kind when there is one. */
  toggleUnderlying: (leg: NewLeg) => void;
  setQty: (id: string, qty: number) => void;
  flip: (id: string) => void;
  remove: (id: string) => void;
  /** Sets the entry price of a FUT / CASH leg (chart click). */
  setEntry: (id: string, entry: number) => void;
  /** Presets and ADD TO BASKET: replaces the option legs, keeps FUT / CASH legs when `keepUnderlying`. */
  replaceLegs: (legs: NewLeg[], keepUnderlying?: boolean) => void;
  setLevels: (patch: Partial<BasketLevels>) => void;
  reset: () => void;
}

const BasketCtx = createContext<Basket | null>(null);

let seq = 0;
const nextId = () => `leg-${Date.now().toString(36)}-${(seq += 1)}`;

const sameContract = (a: Pick<BasketLeg, "kind" | "strike" | "expiry">, b: Pick<BasketLeg, "kind" | "strike" | "expiry">) =>
  a.kind === b.kind && a.strike === b.strike && a.expiry === b.expiry;

const TOO_MANY = `The paper engine takes at most ${MAX_LEGS} legs.`;
const EMPTY_LEVELS: BasketLevels = { stop: null, target: null, cashEntry: null };

export function BasketProvider({ symbol, children }: { symbol: string; children: ReactNode }) {
  const [state, setState] = useState<{ sym: string; legs: BasketLeg[]; levels: BasketLevels; open: boolean; refused: string | null }>(
    { sym: symbol, legs: [], levels: EMPTY_LEVELS, open: false, refused: null });
  // A new symbol starts an empty basket (the legs belong to the old underlying).
  const cur = state.sym === symbol ? state : { sym: symbol, legs: [], levels: EMPTY_LEVELS, open: false, refused: null };

  const edit = useCallback((fn: (legs: BasketLeg[]) => BasketLeg[] | string) => {
    setState((s0) => {
      const s = s0.sym === symbol ? s0 : { sym: symbol, legs: [], levels: EMPTY_LEVELS, open: false, refused: null };
      const out = fn(s.legs);
      if (typeof out === "string") return { ...s, refused: out };
      return { ...s, legs: out, refused: null, open: s.open || out.length > 0 };
    });
  }, [symbol]);

  const api = useMemo<Basket>(() => ({
    legs: cur.legs,
    levels: cur.levels,
    open: cur.open,
    refused: cur.refused,
    setOpen: (open) => setState((s) => ({ ...(s.sym === symbol ? s : { sym: symbol, legs: [], levels: EMPTY_LEVELS, refused: null }), open })),
    toggleOption: (leg) => edit((legs) => {
      const i = legs.findIndex((l) => sameContract(l, leg));
      if (i >= 0) return legs[i].side === leg.side ? legs.filter((_, k) => k !== i) : legs.map((l, k) => (k === i ? { ...l, side: leg.side } : l));
      return legs.length >= MAX_LEGS ? TOO_MANY : [...legs, { ...leg, id: nextId() }];
    }),
    toggleUnderlying: (leg) => edit((legs) => {
      if (legs.some((l) => l.kind === leg.kind)) return legs.filter((l) => l.kind !== leg.kind);
      return legs.length >= MAX_LEGS ? TOO_MANY : [...legs, { ...leg, id: nextId() }];
    }),
    setQty: (id, qty) => edit((legs) => legs.map((l) => (l.id === id ? { ...l, qty: Math.max(1, Math.round(qty)) } : l))),
    flip: (id) => edit((legs) => legs.map((l) => (l.id === id ? { ...l, side: l.side === "B" ? "S" : "B" } : l))),
    remove: (id) => edit((legs) => legs.filter((l) => l.id !== id)),
    setEntry: (id, entry) => edit((legs) => legs.map((l) => (l.id === id && (l.kind === "FUT" || l.kind === "CASH") ? { ...l, entry } : l))),
    replaceLegs: (next, keepUnderlying = true) => edit((legs) => {
      const kept = keepUnderlying ? legs.filter((l) => (l.kind === "FUT" || l.kind === "CASH") && !next.some((n) => n.kind === l.kind)) : [];
      const all = [...kept, ...next.map((n) => ({ ...n, id: nextId() }))];
      return all.length > MAX_LEGS ? TOO_MANY : all;
    }),
    setLevels: (patch) => setState((s) => ({ ...(s.sym === symbol ? s : { sym: symbol, legs: [], open: false, refused: null, levels: EMPTY_LEVELS }), levels: { ...(s.sym === symbol ? s.levels : EMPTY_LEVELS), ...patch } })),
    reset: () => setState({ sym: symbol, legs: [], levels: EMPTY_LEVELS, open: cur.open, refused: null }),
  }), [cur.legs, cur.levels, cur.open, cur.refused, edit, symbol]);

  return <BasketCtx.Provider value={api}>{children}</BasketCtx.Provider>;
}

export function useBasket(): Basket {
  const b = useContext(BasketCtx);
  if (!b) throw new Error("useBasket outside BasketProvider");
  return b;
}

// ── helpers every part uses the same way ─────────────────────────────────

export const isOption = (l: Pick<BasketLeg, "kind">) => l.kind === "CE" || l.kind === "PE";

/** "BUY 4300 CE · 25 Nov" style names, the design's leg labels. */
export function legName(l: BasketLeg, symbol: string, fmtExpiry: (iso: string) => string): string {
  if (l.kind === "CASH") return `Cash · ${symbol}`;
  if (l.kind === "FUT") return `Future · ${l.expiry ? fmtExpiry(l.expiry) : "—"}`;
  return `${l.strike} ${l.kind} · ${l.expiry ? fmtExpiry(l.expiry) : "—"}`;
}

/** The leg as the payoff / margin / paper routes take it (POST /api/desk/strategy/payoff `legs[]`). */
export function toRouteLeg(l: BasketLeg, underlying: string) {
  return {
    kind: l.kind === "CASH" ? ("cash" as const) : l.kind === "FUT" ? ("future" as const) : ("option" as const),
    side: l.side === "B" ? ("buy" as const) : ("sell" as const),
    quantity: l.qty,
    lot_size: l.lotSize,
    entry_price: l.entry,
    expiry: l.expiry,
    strike: l.strike,
    option_type: l.kind === "CE" ? ("call" as const) : l.kind === "PE" ? ("put" as const) : null,
    price_source: l.priceSource,
    underlying,
  };
}
