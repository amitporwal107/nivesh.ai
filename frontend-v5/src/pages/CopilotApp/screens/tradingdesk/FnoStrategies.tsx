/**
 * Smart trading desk — Options & futures lab · Paper strategies (design: "SYM ·
 * expiry", three cards Futures / Options / Cash · delivery, "Why these", the
 * table for every F&O underlying). Rules-based paper ideas, worked out here from
 * three real inputs; nothing places an order.
 *
 *   build-up                       GET /api/fno/scan/buildup   (useBuildup, fno-buildup.ts): the stock future's price
 *                                                                change × the change in its open interest, end of day
 *   OI walls, ATM IV, expected     GET /api/fno/{symbol}/chain (trading/fno.ts, passed in): the strikes with the most
 *   move, option closes                                          put and call OI, the model IV at the ATM strike, the
 *                                                                ATM straddle, each contract's end-of-day close
 *   futures settle                 GET /api/fno/{symbol}/futures (passed in)
 *   an index's build-up            the scan's `indices` row (indexRowFor): the same source as the stats tile and the index cards
 *   Cash · delivery → paper trade  POST /api/desk/paper-trades  { symbol, quantity, entry_price, stop_price,
 *                                                                target_price, source: { kind: "fno-lab", bucket, signal_date } }
 *
 * The rules (also listed on screen under "Why these"):
 *   1. The strategy names come from the build-up alone:
 *        long build-up    → Long futures   · Bull call spread · Delivery long
 *        short build-up   → Short futures  · Bear put spread  · none
 *        short covering   → none           · Bull call spread · none
 *        long unwinding   → none           · Bear put spread  · none
 *        neutral          → none           · Iron condor      · none
 *      Futures only when open interest rose (fresh positions); options as
 *      defined-risk spreads; delivery only on long build-up, and never for an index.
 *   2. Levels come from the OI walls: a long idea stops at the put wall and aims
 *      at the call wall (a short one the other way round). A wall on the wrong
 *      side of the price is replaced by the edge of the expected move.
 *   3. Implied volatility sets how far a spread reaches: the short strike sits at
 *      the wall, or at the listed strike nearest the edge of the expected move
 *      (the ATM straddle) when the wall is further than that. An iron condor is
 *      only suggested when both walls sit outside the expected move.
 * Every figure is per unit from end-of-day closes; one lot = the route's lot size.
 *
 * The desk's paper trades hold long share positions only, so only Cash ·
 * delivery can be recorded (one lot's worth of shares at the close, stop and
 * target from rule 2). Futures and Options keep the button, disabled, and say why.
 */
import { useMemo, useState, type KeyboardEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { StockIcon } from "../../components/EntityIcon";
import { Btn, Pill, TONE_COLOR, fmtNum, fmtPct, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { fmtLevel } from "../trading/PayoffResult";
import { isIndexUnderlying, FNO_INDICES, type ChainState, type FnoChain, type FnoStrike } from "../trading/fno";
import { SEBI_FNO_NOTE, fmtDay, fmtPrice } from "../trading/parts";
import { useDesk } from "./context";
import { writeProblem } from "./desk-trading";
import { BUILDUP_META, buildupRowFor, indexRowFor, useBuildup, type BuildupLabel } from "./fno-buildup";
import { CardHead, FnoGate, TONE_LINE, TONE_SOFT, shortDay, type NearFuture } from "./fno-parts";

export type StrategyKind = "futures" | "options" | "cash";

export const STRATEGY_KINDS: Array<{ kind: StrategyKind; title: string }> = [
  { kind: "futures", title: "Futures" },
  { kind: "options", title: "Options" },
  { kind: "cash", title: "Cash · delivery" },
];

export const NO_TRADE = "No trade suggested";

/** Rule 1: the three strategy names for a build-up label; null = no trade suggested. */
export function strategyNames(label: BuildupLabel | null, index: boolean): Record<StrategyKind, string | null> {
  switch (label) {
    case "long_buildup": return { futures: "Long futures", options: "Bull call spread", cash: index ? null : "Delivery long" };
    case "short_buildup": return { futures: "Short futures", options: "Bear put spread", cash: null };
    case "short_covering": return { futures: null, options: "Bull call spread", cash: null };
    case "long_unwinding": return { futures: null, options: "Bear put spread", cash: null };
    case "neutral": return { futures: null, options: "Iron condor", cash: null };
    default: return { futures: null, options: null, cash: null };
  }
}

/** The colour a strategy name is drawn in: rising ideas mint, falling ones danger, range-bound indigo. */
export function strategyTone(name: string | null): Tone {
  if (!name) return "ink";
  if (/long|bull/i.test(name)) return "mint";
  if (/short|bear/i.test(name)) return "danger";
  return "indigo";
}

// ── the loaded underlying's details ──────────────────────────────────────

export interface KV {
  k: string;
  v: string;
  tone?: Tone;
}

/** POST /api/desk/paper-trades for an idea from the lab — the route's body, with the lab named as the source. */
export interface LabPaperTrade {
  symbol: string;
  quantity: number;
  entry_price: number;
  stop_price: number;
  target_price: number;
  source: { kind: "fno-lab"; bucket: string; signal_date?: string };
}

export interface StrategyCard {
  kind: StrategyKind;
  /** null = no trade suggested. */
  name: string | null;
  /** Mono lines, one per leg. */
  legs: string[];
  /** Four figures (2 × 2). */
  kv: KV[];
  /** One or two plain sentences: why this idea, or why none. */
  text: string;
  /** Cash · delivery only: the paper trade the button records; null when it cannot be recorded. */
  paper: LabPaperTrade | null;
  /** Why the button cannot record it. */
  blocked: string | null;
}

export interface StrategyInput {
  symbol: string;
  index: boolean;
  label: BuildupLabel | null;
  chain: FnoChain;
  /** The nearest future's settle price and expiry; null without futures. */
  future: { settle: number | null; expiry: string } | null;
  /** The bhavcopy day, sent as the trade's signal date. */
  asOf: string;
  /** Why there is no future when `future` is null ("Loading the futures", "The futures didn’t load", …). */
  futuresNote: string;
}

const DASH = "—";
/** Paper levels go to the route in rupees and paise. */
const paise = (n: number) => Math.round(n * 100) / 100;
const lvl = (n: number | null) => (n == null ? DASH : fmtNum(n, 2));
const rr = (reward: number | null, risk: number | null) => (reward != null && risk != null && risk > 0 && reward > 0 ? `${fmtNum(reward / risk, 1)} : 1` : DASH);

/** Rule 2: a stop and a target for a long (up) or short (down) idea from `entry`, the walls and the expected move. */
export function levelsFrom(entry: number, up: boolean, putWall: number | null, callWall: number | null, move: number | null): { stop: number | null; target: number | null; stopFrom: string; targetFrom: string } {
  const below = up ? putWall : callWall;
  const above = up ? callWall : putWall;
  const stopOk = below != null && (up ? below < entry : below > entry);
  const targetOk = above != null && (up ? above > entry : above < entry);
  const stop = stopOk ? below : move != null ? (up ? entry - move : entry + move) : null;
  const target = targetOk ? above : move != null ? (up ? entry + move : entry - move) : null;
  return {
    stop: stop != null && stop > 0 ? stop : null,
    target: target != null && target > 0 ? target : null,
    stopFrom: stopOk ? (up ? "the put wall" : "the call wall") : "the edge of the expected move",
    targetFrom: targetOk ? (up ? "the call wall" : "the put wall") : "the edge of the expected move",
  };
}

const closeOf = (row: FnoStrike | undefined, call: boolean): number | null => {
  const c = (call ? row?.call : row?.put)?.close;
  return c != null && c > 0 ? c : null;
};

/**
 * Rule 3: the short strike of a spread — the wall when it sits on the right side
 * of the ATM strike and inside the expected move, else the listed strike nearest
 * the edge of the expected move (on the right side of the ATM strike).
 */
export function spreadStrike(chain: FnoChain, up: boolean): { strike: number; from: "wall" | "move" } | null {
  const s = chain.summary;
  const atm = s.atm_strike;
  if (atm == null) return null;
  const wall = up ? s.max_call_oi?.strike ?? null : s.max_put_oi?.strike ?? null;
  const spot = s.spot ?? atm;
  const edge = s.expected_move != null ? (up ? spot + s.expected_move : spot - s.expected_move) : null;
  if (wall != null && (up ? wall > atm : wall < atm) && (edge == null || (up ? wall <= edge : wall >= edge))) return { strike: wall, from: "wall" };
  if (edge == null) return null;
  const side = chain.strikes.filter((r) => (up ? r.strike > atm : r.strike < atm));
  if (!side.length) return null;
  const nearest = side.reduce((a, b) => (Math.abs(b.strike - edge) < Math.abs(a.strike - edge) ? b : a));
  return { strike: nearest.strike, from: "move" };
}

function futuresCard(inp: StrategyInput, name: string | null, investor: boolean): StrategyCard {
  const lot = inp.chain.lot_size ?? null;
  const base = { kind: "futures" as const, name, paper: null, blocked: "Paper trades hold shares only for now, so a futures idea cannot be recorded." };
  if (!name) {
    return { ...base, legs: [], kv: [], text: noTradeText("futures", inp, investor) };
  }
  const up = name === "Long futures";
  const settle = inp.future?.settle ?? null;
  const s = inp.chain.summary;
  if (settle == null || !inp.future) {
    return { ...base, legs: [], kv: [], text: `No entry price for this idea: ${inp.futuresNote.charAt(0).toLowerCase()}${inp.futuresNote.slice(1)}.` };
  }
  const lv = levelsFrom(settle, up, s.max_put_oi?.strike ?? null, s.max_call_oi?.strike ?? null, s.expected_move ?? null);
  const reward = lv.target != null ? Math.abs(lv.target - settle) : null;
  const risk = lv.stop != null ? Math.abs(settle - lv.stop) : null;
  return {
    ...base,
    legs: [`${up ? "Long" : "Short"} 1 lot${lot ? ` (${fmtNum(lot)})` : ""} · ${inp.symbol} ${shortDay(inp.future.expiry)} FUT @ ${lvl(settle)}`],
    kv: [
      { k: investor ? "Price now" : "Entry · settle", v: lvl(settle) },
      { k: investor ? "Exit if wrong" : "Stop", v: lvl(lv.stop), tone: "danger" },
      { k: investor ? "Aim" : "Target", v: lvl(lv.target), tone: "mint" },
      { k: investor ? "Reward for risk" : "Reward : risk", v: rr(reward, risk) },
    ],
    text: `Stop at ${lv.stopFrom}${lv.stop != null ? ` (${lvl(lv.stop)})` : ""}, target at ${lv.targetFrom}${lv.target != null ? ` (${lvl(lv.target)})` : ""}.${lot && reward != null && risk != null ? ` One lot risks ₹${fmtNum(risk * lot)} to make ₹${fmtNum(reward * lot)}.` : ""}`,
  };
}

function optionsCard(inp: StrategyInput, name: string | null, investor: boolean): StrategyCard {
  const lot = inp.chain.lot_size ?? null;
  const base = { kind: "options" as const, name, paper: null, blocked: "Paper trades hold shares only for now, so an options idea cannot be recorded." };
  if (!name) return { ...base, legs: [], kv: [], text: noTradeText("options", inp, investor) };
  const c = inp.chain;
  const s = c.summary;
  const exp = shortDay(s.expiry);
  const row = (k: number) => c.strikes.find((r) => r.strike === k);
  const perLot = (pts: number | null) => (lot && pts != null ? ` (₹${fmtNum(pts * lot)} a lot)` : "");

  if (name === "Iron condor") {
    const sp = s.max_put_oi?.strike ?? null;
    const sc = s.max_call_oi?.strike ?? null;
    const spot = s.spot;
    const em = s.expected_move ?? null;
    if (sp == null || sc == null || spot == null || !(sp < spot && spot < sc)) {
      return { ...base, name: null, legs: [], kv: [], text: "Neutral build-up, but the price is not between the put wall and the call wall, so no range idea fits." };
    }
    if (em != null && (sc - spot < em || spot - sp < em)) {
      return { ...base, name: null, legs: [], kv: [], text: `Neutral build-up, but the expected move (±${fmtNum(em, 2)}) reaches past a wall (${fmtLevel(sp)} – ${fmtLevel(sc)}), so a range idea is not suggested.` };
    }
    const idx = (k: number) => c.strikes.findIndex((r) => r.strike === k);
    const lp = c.strikes[idx(sp) - 1];
    const lc = c.strikes[idx(sc) + 1];
    const pS = closeOf(row(sp), false);
    const pL = closeOf(lp, false);
    const cS = closeOf(row(sc), true);
    const cL = closeOf(lc, true);
    const legs = [
      `Short ${fmtLevel(sp)} PE @ ${lvl(pS)}`,
      lp ? `Long ${fmtLevel(lp.strike)} PE @ ${lvl(pL)}` : "Long put below — no strike listed",
      `Short ${fmtLevel(sc)} CE @ ${lvl(cS)}`,
      lc ? `Long ${fmtLevel(lc.strike)} CE @ ${lvl(cL)}` : "Long call above — no strike listed",
    ].map((l) => `${l} · ${exp}`);
    if (!lp || !lc || pS == null || pL == null || cS == null || cL == null) {
      return { ...base, legs, kv: [], text: "Some of the four contracts have no closing price, so the credit cannot be worked out." };
    }
    const credit = pS - pL + (cS - cL);
    const width = Math.max(sp - lp.strike, lc.strike - sc);
    const maxLoss = width - credit;
    return {
      ...base,
      legs,
      kv: [
        { k: investor ? "Received" : "Net credit", v: lvl(credit), tone: credit > 0 ? "mint" : "danger" },
        { k: investor ? "Most it can make" : "Max profit", v: lvl(credit > 0 ? credit : null), tone: "mint" },
        { k: investor ? "Most it can lose" : "Max loss", v: lvl(maxLoss > 0 ? maxLoss : null), tone: "danger" },
        { k: "Breakevens", v: credit > 0 ? `${fmtNum(sp - credit, 0)} – ${fmtNum(sc + credit, 0)}` : DASH },
      ],
      text: credit > 0
        ? `Short strikes at the walls, both outside the expected move. Keeps the credit${perLot(credit)} if the price ends between the walls at expiry.`
        : "The closes give no credit for this condor, so it is shown for reference only.",
    };
  }

  // Bull call spread / bear put spread.
  const up = name === "Bull call spread";
  const atm = s.atm_strike;
  const far = spreadStrike(c, up);
  if (atm == null || !far) {
    return { ...base, legs: [], kv: [], text: "The chain has no ATM strike or no strike on the far side, so the spread cannot be placed." };
  }
  const near = closeOf(row(atm), up);
  const away = closeOf(row(far.strike), up);
  const typ = up ? "CE" : "PE";
  const legs = [`Long ${fmtLevel(atm)} ${typ} @ ${lvl(near)} · ${exp}`, `Short ${fmtLevel(far.strike)} ${typ} @ ${lvl(away)} · ${exp}`];
  if (near == null || away == null || near <= away) {
    return { ...base, legs, kv: [], text: "One of the two contracts has no closing price (or the spread costs nothing), so its cost cannot be worked out." };
  }
  const debit = near - away;
  const width = Math.abs(far.strike - atm);
  const maxProfit = width - debit;
  const breakeven = up ? atm + debit : atm - debit;
  return {
    ...base,
    legs,
    kv: [
      { k: investor ? "Cost" : "Net debit", v: lvl(debit), tone: "danger" },
      { k: investor ? "Most it can make" : "Max profit", v: lvl(maxProfit > 0 ? maxProfit : null), tone: "mint" },
      { k: investor ? "Most it can lose" : "Max loss", v: lvl(debit), tone: "danger" },
      { k: investor ? "Needs to pass" : "Breakeven", v: fmtNum(breakeven, 2) },
    ],
    text: `Short leg at ${far.from === "wall" ? `the ${up ? "call" : "put"} wall` : "the strike nearest the edge of the expected move"} (${fmtLevel(far.strike)}). The most it can lose is the cost${perLot(debit)}.`,
  };
}

function cashCard(inp: StrategyInput, name: string | null, investor: boolean): StrategyCard {
  const base = { kind: "cash" as const, name };
  if (!name) {
    return {
      ...base, legs: [], kv: [], paper: null,
      text: noTradeText("cash", inp, investor),
      blocked: NO_TRADE,
    };
  }
  const s = inp.chain.summary;
  const spot = s.spot;
  const lot = inp.chain.lot_size ?? null;
  if (spot == null) {
    return { ...base, legs: [], kv: [], paper: null, text: "The bhavcopy sent no price for the stock, so there is no entry.", blocked: "No entry price." };
  }
  const lv = levelsFrom(spot, true, s.max_put_oi?.strike ?? null, s.max_call_oi?.strike ?? null, s.expected_move ?? null);
  const kv: KV[] = [
    { k: investor ? "Buy near" : "Entry · close", v: lvl(spot) },
    { k: investor ? "Exit if wrong" : "Stop", v: lvl(lv.stop), tone: "danger" },
    { k: investor ? "Aim" : "Target", v: lvl(lv.target), tone: "mint" },
    { k: investor ? "Shares" : "Quantity", v: lot ? fmtNum(lot) : DASH },
  ];
  const legs = [`Long ${lot ? fmtNum(lot) : "—"} shares · ${inp.symbol} @ ${lvl(spot)}`];
  let blocked: string | null = null;
  if (lot == null) blocked = "The route sent no lot size, so the quantity (one lot’s worth of shares) is unknown.";
  else if (lv.stop == null || lv.target == null) blocked = "Needs a stop below and a target above the price; the chain gives neither wall nor expected move.";
  const paper: LabPaperTrade | null = blocked || lot == null || lv.stop == null || lv.target == null
    ? null
    : {
        symbol: inp.symbol,
        quantity: lot,
        entry_price: paise(spot),
        stop_price: paise(lv.stop),
        target_price: paise(lv.target),
        source: { kind: "fno-lab", bucket: "Cash · delivery · long build-up", signal_date: inp.asOf },
      };
  return {
    ...base, legs, kv, paper, blocked,
    text: `One lot’s worth of shares, held for delivery. Stop at ${lv.stopFrom}, target at ${lv.targetFrom}. Recorded as a paper trade only, marked against end-of-day closes.`,
  };
}

function noTradeText(kind: StrategyKind, inp: StrategyInput, investor: boolean): string {
  if (inp.label == null) {
    return inp.index
      ? "The build-up scan has no index-futures row for this index on the latest day, so the rules suggest nothing."
      : "This stock has no build-up reading on the latest day, so the rules suggest nothing.";
  }
  if (kind === "futures") return investor ? "Open bets fell, so the move is people closing positions, not new ones. No futures idea." : "Open interest fell: the move is positions closing, not fresh ones. The rules take futures only on fresh positions.";
  if (kind === "cash") return inp.index ? "An index has no shares to hold for delivery." : "The rules take delivery only on long build-up (price and open interest both up).";
  return "No options idea for this reading.";
}

/** The three cards for the loaded underlying. */
export function strategyCards(inp: StrategyInput, investor: boolean): StrategyCard[] {
  const names = strategyNames(inp.label, inp.index);
  return [futuresCard(inp, names.futures, investor), optionsCard(inp, names.options, investor), cashCard(inp, names.cash, investor)];
}

// ── recording the cash idea ──────────────────────────────────────────────

/**
 * POST /api/desk/paper-trades with the lab named as the source. The same route
 * and the same cache as desk-trading.ts (whose body type names the scanner as
 * the only source), so the Portfolio tab's paper-trade list refreshes after it.
 */
export function useAddLabPaperTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: LabPaperTrade): Promise<void> => {
      await http({ method: "POST", path: "/api/desk/paper-trades", body, noRetry: true });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["copilot", "desk", "paper-trades"] }),
  });
}

// ── the view ─────────────────────────────────────────────────────────────

const ROWS_FIRST = 12;
const TABLE_TEMPLATE = "minmax(0,1.3fr) minmax(0,1.2fr) minmax(0,1fr) minmax(0,1.1fr) minmax(0,1fr)";
const headStyle = { fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)" } as const;

function BuildupPill({ label, testId }: { label: BuildupLabel | null; testId?: string }) {
  if (!label) return <span data-testid={testId} className="cp-pill" title="No build-up reading for this underlying">Build-up —</span>;
  const m = BUILDUP_META[label];
  return <span data-testid={testId} className="cp-pill" data-tone={m.tone}>{m.label}</span>;
}

function Card({ card, symbol }: { card: StrategyCard; symbol: string }) {
  const { openTab } = useDesk();
  const add = useAddLabPaperTrade();
  const id = `desk-fno-strat-${card.kind}`;
  const title = STRATEGY_KINDS.find((k) => k.kind === card.kind)?.title ?? card.kind;
  const tone = strategyTone(card.name);
  const canAdd = card.kind === "cash" && card.paper != null;
  const done = add.variables?.symbol === symbol ? add : null;
  const p = card.paper;
  const note = !card.name
    ? null
    : canAdd && p
      ? `Simulated: ${fmtNum(p.quantity)} shares at ${fmtPrice(p.entry_price)}, stop ${fmtPrice(p.stop_price)}, target ${fmtPrice(p.target_price)}. No order is placed; it is marked against end-of-day closes.`
      : card.blocked;
  return (
    <section data-testid={id} data-strategy={card.name ?? ""} className="cp-card flex min-w-0 flex-col" style={{ gap: 12, padding: "16px 18px" }}>
      <span className="cp-eyebrow">{title}</span>
      <span data-testid={`${id}-name`} style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.1, letterSpacing: "-0.02em", color: card.name ? TONE_COLOR[tone] : "var(--cp-ink-3)" }}>
        {card.name ?? NO_TRADE}
      </span>
      {card.legs.length > 0 && (
        <div data-testid={`${id}-legs`} className="flex flex-col" style={{ gap: 3 }}>
          {card.legs.map((l) => <span key={l} className="cp-num" style={{ fontSize: 11, lineHeight: 1.45, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{l}</span>)}
        </div>
      )}
      {card.kv.length > 0 && (
        <div data-testid={`${id}-kv`} className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 6 }}>
          {card.kv.map((kv) => (
            <div key={kv.k} className="flex min-w-0 flex-col" style={{ gap: 3, padding: "9px 11px", borderRadius: 10, background: "var(--bg-2)", border: "1px solid var(--cp-line)" }}>
              <span className="cp-eyebrow" style={{ fontSize: 9 }}>{kv.k}</span>
              <span data-testid={`${id}-kv-value`} data-k={kv.k} className="cp-num" style={{ fontSize: 14, color: kv.v === DASH ? "var(--cp-ink-3)" : TONE_COLOR[kv.tone ?? "ink"] }}>{kv.v}</span>
            </div>
          ))}
        </div>
      )}
      <span data-testid={`${id}-text`} style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{card.text}</span>
      <div className="flex flex-col" style={{ gap: 6, marginTop: "auto" }}>
        <Btn
          data-testid={`${id}-add`}
          variant={canAdd ? "primary" : "default"}
          disabled={!canAdd || add.isPending}
          aria-describedby={note ? `${id}-note` : undefined}
          onClick={() => { if (p) add.mutate(p); }}
        >
          {!card.name ? NO_TRADE : add.isPending ? "Adding…" : "Add to paper trades"}
        </Btn>
        {note && <span id={`${id}-note`} data-testid={`${id}-note`} style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{note}</span>}
        {canAdd && done?.isSuccess && (
          <span role="status" data-testid={`${id}-done`} style={{ fontSize: 12, lineHeight: 1.5, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--cp-ink)" }}>
            Paper trade added: {fmtNum(done.variables?.quantity ?? null)} {symbol} at {fmtPrice(done.variables?.entry_price ?? null)}. No order is placed.{" "}
            <button type="button" data-testid={`${id}-open-paper`} onClick={() => openTab("portfolio")} style={{ padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--mint)", cursor: "pointer" }}>
              See your paper trades ›
            </button>
          </span>
        )}
        {canAdd && done?.isError && (
          <span role="alert" data-testid={`${id}-error`} style={{ fontSize: 12, lineHeight: 1.5, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)", color: "var(--cp-ink)" }}>
            Not added — {writeProblem(done.error)}
          </span>
        )}
      </div>
    </section>
  );
}

/** "Why these": the rules with this underlying's own figures. */
function whyLines(symbol: string, label: BuildupLabel | null, price: number | null, oi: number | null, asOf: string | null, chain: FnoChain, investor: boolean): string[] {
  const s = chain.summary;
  const out: string[] = [];
  if (label) {
    const m = BUILDUP_META[label];
    out.push(investor
      ? `${m.label}: ${m.plain.toLowerCase()} (price ${fmtPct(price, { signed: true, digits: 2 })}, open bets ${fmtPct(oi, { signed: true, digits: 2 })}${asOf ? `, ${fmtDay(asOf)}` : ""}).`
      : `${m.label}${asOf ? ` on ${fmtDay(asOf)}` : ""}: the future’s price ${fmtPct(price, { signed: true, digits: 2 })}, its open interest ${fmtPct(oi, { signed: true, digits: 2 })} over every expiry.`);
  } else {
    out.push(isIndexUnderlying(symbol)
      ? `${symbol} is an index: the build-up scan has no index-futures row for it on the latest day, so no strategy is named.`
      : `${symbol} has no build-up reading on the latest day, so no strategy is named.`);
  }
  if (s.max_put_oi || s.max_call_oi) {
    out.push(`Walls: the most put open interest is at ${s.max_put_oi ? fmtLevel(s.max_put_oi.strike) : "—"} (stops for rising ideas) and the most call open interest at ${s.max_call_oi ? fmtLevel(s.max_call_oi.strike) : "—"} (targets).`);
  }
  if (s.expected_move != null) {
    out.push(`${s.atm_iv != null ? `ATM implied volatility ${fmtNum(s.atm_iv, 2)}%: t` : "T"}he ATM straddle prices a swing of ±${fmtNum(s.expected_move, 2)}${s.expected_move_pct != null ? ` (${fmtNum(s.expected_move_pct, 2)}%)` : ""} to ${fmtDay(s.expiry)}. A spread’s short strike goes at the wall, or at the edge of that swing when the wall is further; an iron condor needs both walls outside it.`);
  }
  out.push("Futures only when open interest rose (fresh positions); options as defined-risk spreads; delivery only on long build-up.");
  out.push(`Prices are end-of-day closes per unit${chain.lot_size ? `; one lot is ${fmtNum(chain.lot_size)} units` : ""}.`);
  return out;
}

export function StrategiesView({ symbol, state, near, futuresNote, onLoad }: { symbol: string; state: ChainState; near: NearFuture | null; futuresNote: string; onLoad: (s: string) => void }) {
  const { mobile } = useCopilotShell();
  const { persona } = useDesk();
  const investor = persona === "investor";
  const scan = useBuildup(true);
  const [all, setAll] = useState(false);
  const index = isIndexUnderlying(symbol);
  // An index reads its build-up from the scan's index-futures row: the same source as the stats tile and the index cards.
  const row = index ? indexRowFor(scan.data, symbol) : buildupRowFor(scan.data, symbol);
  const label = row?.label ?? null;
  const chain = state.status === "ok" ? state.chain : null;
  const cards = useMemo(
    () => (chain ? strategyCards({ symbol, index, label, chain, future: near ? { settle: near.future.settle, expiry: near.future.expiry } : null, asOf: chain.summary.as_of, futuresNote }, investor) : []),
    [chain, symbol, index, label, near, futuresNote, investor],
  );

  const tableRows: Array<{ symbol: string; label: BuildupLabel | null; index: boolean }> = [
    ...FNO_INDICES.map((i) => ({ symbol: i.symbol as string, label: indexRowFor(scan.data, i.symbol)?.label ?? null, index: true })),
    ...(scan.data?.rows ?? []).map((r) => ({ symbol: r.symbol, label: r.label, index: false })),
  ];
  const shown = all ? tableRows : tableRows.slice(0, ROWS_FIRST);
  const onKey = (e: KeyboardEvent, sym: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onLoad(sym);
    }
  };

  return (
    <div data-testid="desk-fno-strategies" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
        <span className="flex items-center" style={{ gap: 10 }}>
          {!index && <StockIcon symbol={symbol} size={24} />}
          <span data-testid="desk-fno-strat-title" style={{ fontFamily: "var(--display)", fontSize: mobile ? 22 : 26, lineHeight: 1.1, letterSpacing: "-0.02em" }}>
            {symbol} · {chain ? shortDay(chain.summary.expiry) : "—"}
          </span>
        </span>
        <BuildupPill label={label} testId="desk-fno-strat-buildup" />
        <span className="cp-eyebrow" data-testid="desk-fno-strat-kind" style={{ marginLeft: "auto" }}>Rules-based · paper trading only</span>
      </div>

      <FnoGate symbol={symbol} state={state} testId="desk-fno-strat">
        {(c) => (
          <>
            <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "repeat(3,minmax(0,1fr))", gap: 12, alignItems: "stretch" }}>
              {cards.map((card) => <Card key={card.kind} card={card} symbol={symbol} />)}
            </div>
            <section data-testid="desk-fno-strat-why" className="cp-card flex flex-col" style={{ gap: 10, padding: "16px 18px" }}>
              <span className="cp-eyebrow">Why these</span>
              <ul className="m-0 flex flex-col" style={{ gap: 8, padding: 0, listStyle: "none" }}>
                {whyLines(symbol, label, row?.priceChgPct ?? null, row?.oiChgPct ?? null, scan.data?.asOf ?? null, c, investor).map((l) => (
                  <li key={l} className="flex" style={{ gap: 8, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
                    <span aria-hidden="true" style={{ color: "var(--mint)" }}>›</span>
                    <span>{l}</span>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </FnoGate>

      <section data-testid="desk-fno-strat-table" className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>
        <CardHead testId="desk-fno-strat-table-head" meta={scan.data ? `${fmtNum(tableRows.length)} underlyings · names from build-up alone` : undefined}>
          Paper strategy for every F&amp;O underlying
        </CardHead>
        {scan.isPending && <div style={{ padding: 18, fontSize: 13, color: "var(--cp-ink-3)" }}>Reading the build-up scan…</div>}
        {scan.isError && (
          <div role="alert" data-testid="desk-fno-strat-table-error" style={{ padding: 18, fontSize: 13, color: "var(--cp-ink-3)" }}>
            The build-up scan didn’t load, so the stock rows are missing.{" "}
            <button type="button" onClick={() => scan.refetch()} style={{ padding: 0, border: 0, background: "none", fontSize: 13, color: "var(--cp-ink)", cursor: "pointer" }}>Retry ›</button>
          </div>
        )}
        <div className="cp-scroll overflow-x-auto" role="table" aria-label="Paper strategy for every F&O underlying">
          <div style={{ minWidth: 600 }}>
            <div role="row" className="grid" style={{ gridTemplateColumns: TABLE_TEMPLATE, gap: 12, padding: "10px 18px" }}>
              {["Underlying", "Build-up", "Futures", "Options", "Cash"].map((h) => <span key={h} role="columnheader" style={headStyle}>{h}</span>)}
            </div>
            {shown.map((r) => {
              const names = strategyNames(r.label, r.index);
              const on = r.symbol === symbol;
              const nameCell = (n: string | null, k: StrategyKind) => (
                <span role="cell" data-col={k} style={{ fontSize: 12.5, color: n ? TONE_COLOR[strategyTone(n)] : "var(--cp-ink-4)", minWidth: 0 }}>{n ?? "—"}</span>
              );
              return (
                <div
                  key={r.symbol}
                  role="row"
                  tabIndex={0}
                  data-testid="desk-fno-strat-row"
                  data-symbol={r.symbol}
                  data-loaded={on ? "true" : undefined}
                  title={`Load ${r.symbol}`}
                  onClick={() => onLoad(r.symbol)}
                  onKeyDown={(e) => onKey(e, r.symbol)}
                  className="cp-row-link grid items-center"
                  style={{ gridTemplateColumns: TABLE_TEMPLATE, gap: 12, padding: "9px 18px", borderTop: "1px solid var(--cp-line)", background: on ? "var(--bg-2)" : undefined }}
                >
                  <span role="cell" className="flex min-w-0 items-center" style={{ gap: 8 }}>
                    {!r.index && <StockIcon symbol={r.symbol} size={18} />}
                    <span className="cp-num" style={{ fontSize: 12.5, fontWeight: 500, color: "var(--cp-ink)" }}>{r.symbol}</span>
                  </span>
                  <span role="cell" data-col="buildup" style={{ minWidth: 0 }}>
                    {r.label ? <Pill tone={BUILDUP_META[r.label].tone}>{BUILDUP_META[r.label].label}</Pill> : <span style={{ fontSize: 12, color: "var(--cp-ink-4)" }}>—</span>}
                  </span>
                  {nameCell(names.futures, "futures")}
                  {nameCell(names.options, "options")}
                  {nameCell(names.cash, "cash")}
                </div>
              );
            })}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between" style={{ gap: 8, padding: "12px 18px", borderTop: "1px solid var(--cp-line)" }}>
          <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)", flex: "1 1 300px", minWidth: 0 }}>
            Names come from each stock’s build-up alone; the legs and levels above are worked out for the loaded underlying only. An index row reads the scan’s index-futures build-up, "—" when the scan has none. Open a row to load it.
          </span>
          {tableRows.length > ROWS_FIRST && (
            <button type="button" className="cp-chip" data-testid="desk-fno-strat-all" aria-expanded={all} onClick={() => setAll(!all)}>
              {all ? "Show fewer" : `Show all ${fmtNum(tableRows.length)}`}
            </button>
          )}
        </div>
      </section>

      <p data-testid="desk-fno-strat-disclaimer" className="m-0" style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)", padding: "12px 14px", borderRadius: 12, border: `1px solid ${TONE_LINE.amber}`, background: TONE_SOFT.amber }}>
        Rules-based paper ideas from end-of-day data, for learning — not a recommendation to buy or sell. {SEBI_FNO_NOTE} Nivesh cannot place orders.
      </p>
    </div>
  );
}
