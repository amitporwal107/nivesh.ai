/**
 * Smart trading desk — the user's own paper trades and price alerts. These are
 * the desk's only writes, and both are simulated: nothing here places an order
 * or reaches a broker.
 *
 *   GET    /api/desk/paper-trades?status=all          open and closed paper trades with their end-of-day marks
 *                                                     and a summary (backend/routes/desk_trading.py); each trade
 *                                                     carries the DaaS paper_trades field set (PRD §13.4): entry rule
 *                                                     and whether it was reached, observations, MFE / MAE, estimated
 *                                                     costs, gross and net P&L, rule version and flags
 *   POST   /api/desk/paper-trades                     { symbol, quantity, entry_price, stop_price, target_price, source,
 *                                                       entry_rule?, entry_window_sessions?, max_hold_sessions?,
 *                                                       signal_at?, strategy_version?, rationale? } with an
 *                                                     Idempotency-Key header per submission (useSubmissionKey); 409
 *                                                     duplicate_open_trade when the stock already has an open trade
 *   POST   /api/desk/paper-trades/{id}/close          {} — closes at the last close (exit reason "manual"); a trade
 *                                                     whose entry was not reached is cancelled with no P&L
 *                                                     Strategy trades (kind "strategy": futures and option structures, rules desk-paper-v3)
 *                                                     come back in the same list, read into `PaperBook.strategyTrades`:
 *                                                     legs with entry and mark, the immutable signal block, the
 *                                                     lifecycle log, flags, net premium and P&L (StrategyPaperTrade)
 *   POST   /api/desk/paper-trades                     kind "strategy": NewStrategyPaperTrade (useAddStrategyPaperTrade);
 *                                                     nothing in the screens creates one yet (the Strategy Builder will)
 *   GET    /api/desk/paper-trades/{id}                one trade with its lifecycle log and immutable signal (read-only)
 *   GET    /api/desk/alerts?status=all                every alert (price, a new filing, a category, unusual volume, a scanner
 *                                                     entry, a sector move, a risk level), active and fired with the reason it
 *                                                     fired, the session they were checked through and the route's catalogue
 *   POST   /api/desk/alerts                           { condition, ...that condition's fields } (NewDeskAlert); 409
 *                                                     duplicate_alert for an alert the user already has active
 *   DELETE /api/desk/alerts/{id}                      204
 *
 * Marks, exits and alert checks use end-of-day daily bars (high, low, close of
 * the raw traded price). When those cannot be read the lists still answer,
 * with marks null and `marks_error` set; a mark is never made up. A trade whose stop and target are both touched in one
 * session is closed at the stop. Writes go through the app's http client (the
 * session cookie rides along) with no retry, and a failure keeps the server's
 * own words (a 409 limit, a 422 validation message) for the screen to show.
 *
 * Reads trust nothing: a missing or non-numeric field is null, never 0, and a
 * body without the list the route always sends throws a contract error.
 */
import type { PlanRef } from "./strategy/trade-plan";
import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { correlationId } from "@/lib/observability";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "./desk-data";
import { bareReason, detailOf, orderReasons, readReasons, riskBlockedText, type RiskReason } from "./risk-controls";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const price = (v: unknown): number | null => {
  const n = num(v);
  return n != null && n > 0 ? n : null;
};

const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

const PAPER_KEY = ["copilot", "desk", "paper-trades"] as const;
const ALERTS_KEY = ["copilot", "desk", "alerts"] as const;

/** The route's error codes (backend/routes/desk_trading.py) in plain words; the code itself is shown beside them. */
const CODE_TEXT: Record<string, string> = {
  open_trade_limit: "You have the most open paper trades allowed (100). Close one first.",
  active_alert_limit: "You have the most active alerts allowed (50). Delete one first.",
  invalid_symbol: "The symbol is not a valid NSE symbol.",
  invalid_quantity: "The quantity must be a whole number from 1 to 10,00,000.",
  stop_not_below_entry: "The stop must be below the entry.",
  target_not_above_entry: "The target must be above the entry.",
  invalid_source: "The setup details sent with the trade were not accepted.",
  invalid_note: "The note was not accepted.",
  invalid_condition: "That alert type is not one the desk knows.",
  duplicate_alert: "You already have this alert, and it is still active.",
  invalid_level: "The level is not a number the alert can use.",
  invalid_impact: "A filing alert is for every filing or for high-impact ones only.",
  invalid_category: "That category is not one an alert can follow.",
  invalid_multiple: "The volume multiple must be from 1.5 to 20.",
  invalid_stage: "That scanner stage is not one the scanner writes.",
  invalid_index: "That sector index is not one the desk follows.",
  invalid_threshold: "The sector threshold must be from 0.5% to 10%.",
  invalid_direction: "The direction must be up, down or either.",
  invalid_body: "The request was not in the expected form.",
  unknown_field: "The request carried a field the server does not take.",
  trade_not_found: "That paper trade is no longer on record.",
  alert_not_found: "That alert is no longer on record.",
  trade_already_closed: "That paper trade is already closed.",
  invalid_entry_rule: "The entry rule is not one the desk knows (at once, break above, pull back to).",
  invalid_entry_window: "The entry window must be 1 to 20 sessions, and only for an entry that waits for a level.",
  invalid_max_hold: "The most sessions to hold must be a whole number from 1 to 250.",
  invalid_signal_at: "The signal time must be a date or time, not in the future.",
  invalid_strategy_version: "The strategy version was not accepted.",
  invalid_rationale: "The rationale was not accepted.",
  invalid_kind: "That kind of paper trade is not one the desk knows.",
  invalid_family: "That strategy family is not on the desk's list.",
  invalid_leg_count: "A strategy has from 1 to 4 legs.",
  unbounded_loss: "That structure can lose without limit upward. Only defined-risk option structures (and a plain futures leg) are recorded.",
  naked_short_put: "A sold put needs a bought put of at least the same size. Naked short options are not recorded.",
  mixed_option_expiries: "All option legs must expire on the same date.",
  cash_only_use_share_trade: "A strategy needs at least one futures or option leg. Record shares as a share trade.",
  short_cash_not_supported: "Selling shares is not supported in a strategy.",
  expiry_in_past: "A leg's expiry has already passed.",
  entry_rule_not_supported: "A strategy is recorded at the leg prices you give (at once); waiting for a level is not supported.",
  levels_not_supported_neutral: "A neutral strategy has no stop or target on the underlying.",
  invalid_signal: "The signal details (time, rule version, evidence) were not accepted.",
  invalid_evidence_summary: "The evidence summary is required (up to 1000 characters).",
  invalid_rule_version: "The rule version of the signal is required.",
  duplicate_open_trade: "You already have an open paper trade in this stock. Adding to a position is not supported yet; close it first.",
  duplicate_open_structure: "You already have this structure open. Close it before recording it again.",
  idempotency_conflict: "This submission's key was already used for a different paper trade; nothing new was recorded.",
  invalid_idempotency_key: "The submission key was not accepted.",
  short_futures_not_supported: "Short futures are not recorded as paper trades yet.",
  futures_stop_required: "A structure with a futures leg needs a stop on the underlying.",
  lot_size_mismatch: "A leg's lot size is not the exchange lot.",
  lot_size_unverified: "The exchange lot could not be confirmed, so nothing was recorded.",
  no_close_available:  "There is no end-of-day close for this stock yet, so it cannot be closed at the last close.",
  prices_unavailable: "Prices could not be read from the data platform right now.",
  upstream_unavailable: "The data platform could not be reached right now.",
};

/**
 * A 409 `risk_reduce` from a paper write (backend/services/risk_gate/service.py `refusal`): the universal risk policy
 * would take the entry only at a smaller size, and NOTHING was recorded. Shares for a share trade, lots per leg for a
 * structure; a size the body does not carry as a whole number is null. Null for any other error.
 */
export interface RiskReduce {
  approvedQty: number | null;
  approvedLots: number | null;
  requestedQty: number | null;
  requestedLots: number | null;
  approvedNotionalRs: number | null;
  /** The reasons the size was cut, reductions first (info notes only when nothing else was sent). */
  reasons: RiskReason[];
}

const whole = (v: unknown): number | null => {
  const n = num(v);
  return n != null && Number.isInteger(n) && n >= 0 ? n : null;
};

export function riskReduceOf(e: unknown): RiskReduce | null {
  const d = detailOf(e);
  if (d.code !== "risk_reduce") return null;
  const rs = num(d.approved_notional_rs);
  return {
    approvedQty: whole(d.approved_qty),
    approvedLots: whole(d.approved_lots),
    requestedQty: whole(d.requested_qty),
    requestedLots: whole(d.requested_lots),
    approvedNotionalRs: rs != null && rs > 0 ? rs : null,
    reasons: orderReasons(readReasons(d.reasons)),
  };
}

const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;

/** "The risk policy allows at most 59 shares (you asked 85): <reasons>. Nothing was recorded. (risk_reduce)" — null
 *  when the body names no approved size (writeProblem then shows the server's own sentence). */
function riskReduceText(r: RiskReduce): string | null {
  const size = r.approvedQty != null
    ? { at: plural(r.approvedQty, "share", "shares"), asked: r.requestedQty }
    : r.approvedLots != null
      ? { at: `${plural(r.approvedLots, "lot", "lots")} per leg`, asked: r.requestedLots }
      : null;
  if (!size) return null;
  const asked = size.asked != null ? ` (you asked ${size.asked.toLocaleString("en-IN")})` : "";
  const why = r.reasons.length ? `: ${r.reasons.map((x) => bareReason(x.message)).join("; ")}` : "";
  return `The risk policy allows at most ${size.at}${asked}${why}. Nothing was recorded. (risk_reduce)`;
}

/** The server's own words for a failed write: its code in plain words with the code beside it, else its text. A 409
 *  risk_blocked says which control blocked it and where the controls are (riskBlockedText, risk-controls.ts); a 409
 *  risk_reduce names the size the policy allows and why (riskReduceOf). */
export function writeProblem(e: unknown): string {
  if (e instanceof ApiError) {
    const blocked = riskBlockedText(e);
    if (blocked) return blocked;
    const reduce = riskReduceOf(e);
    const reduced = reduce && riskReduceText(reduce);
    if (reduced) return reduced;
    // A refusal sent as {code, message} (a duplicate with the existing trade's id, an exchange lot, funds): the
    // server's own sentence, which names the specifics, with the code beside it.
    const code = str(rec(rec(e.body).detail).code);
    if (code && e.detail && e.detail !== code) return `${e.detail} (${code})`;
    if (e.detail) return CODE_TEXT[e.detail] ? `${CODE_TEXT[e.detail]} (${e.detail})` : e.detail;
    if (e.kind === "network") return "The network request failed.";
    if (e.kind === "timeout") return "The request took too long.";
    return e.message || `HTTP ${e.status ?? "error"}`;
  }
  return e instanceof Error && e.message ? e.message : "The request failed.";
}

// ── paper trades ─────────────────────────────────────────────────────────

/** Exit reasons the route sends (backend/services/exit_rules.py, exit-rules-v1): `trailing_stop` is a stop the opt-in ATR
 *  trail raised (distinct from the initial `stop`), `trend` the opt-in close-below-EMA rule, `risk_control` a risk limit. A
 *  reason not in this list is kept as its raw code (`exitReasonCode`) and shown as such, never dropped. */
export type ExitReason = "stop" | "trailing_stop" | "target" | "time" | "trend" | "manual" | "risk_control" | "entry_not_reached" | "cancelled";
const EXIT_REASONS: readonly string[] = ["stop", "trailing_stop", "target", "time", "trend", "manual", "risk_control", "entry_not_reached", "cancelled"];

/** An opt-in research exit rule enabled on a trade (off by default; never a default until the fixed backtest has tested it). */
export interface ExitRuleLabel {
  code: string;
  version: string | null;
  label: string;
  params: Record<string, unknown>;
}
/** One version of a trade's stop: `session` is the close it was set at (null = at entry), in force from the next session. */
export interface StopVersion {
  session: string | null;
  stop: number;
  reason: string;
  version: number | null;
}

function readExitRules(v: unknown): ExitRuleLabel[] {
  return (Array.isArray(v) ? v : []).flatMap((x): ExitRuleLabel[] => {
    const r = rec(x);
    const code = str(r.code);
    return code ? [{ code, version: str(r.version), label: str(r.label) ?? code, params: rec(r.params) }] : [];
  });
}

function readStopHistory(v: unknown): StopVersion[] {
  return (Array.isArray(v) ? v : []).flatMap((x): StopVersion[] => {
    const r = rec(x);
    const stop = price(r.stop);
    return stop != null ? [{ session: str(r.session), stop, reason: str(r.reason) ?? "initial", version: num(r.version) }] : [];
  });
}

export type EntryRule = "at_once" | "break_above" | "pullback_to";
const ENTRY_RULES: readonly string[] = ["at_once", "break_above", "pullback_to"];

/** How each entry rule fills, in a few words (the FILL MODEL in backend/services/desk_trading.py). */
export const ENTRY_RULE_SHORT: Record<EntryRule, string> = {
  at_once: "filled at once, inside the last session's range",
  break_above: "filled when a later session trades up to it",
  pullback_to: "filled when a later session pulls back to it",
};

/**
 * The entry rule a scanner idea's levels mean, from where the entry sits against the scan's close (the levels the
 * scanner set: backend/services/positional_engine/trade_planner.py and setup_rules.py):
 *   above the close → break_above   EARLY_BREAKOUT's trigger, max(close, 20-day high x 1.001); the watchlist trigger
 *                                   (the breakout level) of a pre-breakout or accumulation setup
 *   below the close → pullback_to   ACCUMULATION's swing-low x 1.01 entry; a confirmed breakout's retest of its level
 *   at the close    → at_once       BREAKOUT (entry = the close), or ACCUMULATION already at support
 * With no close the setup decides: ACCUMULATION → pullback_to; EARLY_BREAKOUT, pre-breakout, accumulation bucket →
 * break_above; anything else → at_once. The route refuses an at-once entry outside the last completed session's range
 * either way (entry_not_tradable), so a level the market never traded is never booked as filled.
 */
export function entryRuleFor(entry: number, close: number | null | undefined,
  setup: { stage?: string | null; bucket?: string | null } = {}): EntryRule {
  if (close != null && close > 0) {
    const tolerance = close * 0.0005;               // the scanner rounds its levels to the paisa
    if (entry > close + tolerance) return "break_above";
    if (entry < close - tolerance) return "pullback_to";
    return "at_once";
  }
  const stage = (setup.stage ?? "").toUpperCase();
  if (stage === "ACCUMULATION") return "pullback_to";
  if (stage === "EARLY_BREAKOUT" || setup.bucket === "pre_breakout" || setup.bucket === "true_accumulation") return "break_above";
  return "at_once";
}
/** The most sessions the route lets a paper trade be held (backend MAX_HOLD_SESSIONS; outside it the route answers 422
 *  invalid_max_hold). */
export const MAX_HOLD_SESSIONS = 250;
/**
 * `max_hold_sessions` for a paper-trade body from a setup's holding window (the scanner's timeframe_days_max, a plan's
 * horizon_days): the time exit closes the trade at the close of that session held. Only a whole number from 1 to
 * MAX_HOLD_SESSIONS is sent; anything else (missing, fractional, out of range) is left out, so the trade has no time exit
 * rather than a made-up one.
 */
export function maxHoldFor(sessions: number | null | undefined): number | undefined {
  return sessions != null && Number.isInteger(sessions) && sessions >= 1 && sessions <= MAX_HOLD_SESSIONS ? sessions : undefined;
}
/** "; exits after N sessions held" for a body's note, or "" when no time exit is sent. */
export function maxHoldNote(sessions: number | undefined): string {
  return sessions != null ? `; exits after ${sessions} session${sessions === 1 ? "" : "s"} held` : "";
}

/** assumed: filled when recorded (at once) · reached: the level traded · waiting: not yet · not_reached: never filled. */
export type EntryStatus = "assumed" | "reached" | "waiting" | "not_reached";
const ENTRY_STATUSES: readonly string[] = ["assumed", "reached", "waiting", "not_reached"];

/** A rule violation or missing data the route found on the trade's price path. */
export interface PaperFlag {
  code: string;
  text: string;
  session: string | null;
  price: number | null;
}

export interface CostModel {
  name: string | null;
  slippagePctPerSide: number | null;
  brokerageRsPerSide: number | null;
  /** "desk-cost-v2" (the desk cost card: statutory charges by segment) or "desk-flat-v1" / null (slippage + brokerage). */
  version: string | null;
}

/** A trade's costs by component, ₹ (backend services/desk_cost_card.py; a flat-model trade has only brokerage and
 *  slippage, the rest 0). */
export interface CostsBreakdown {
  brokerage: number | null;
  stt: number | null;
  exchange: number | null;
  sebi: number | null;
  stamp: number | null;
  gst: number | null;
  slippage: number | null;
  total: number | null;
}

export function readCostsBreakdown(v: unknown): CostsBreakdown | null {
  const b = rec(v);
  if (!Object.keys(b).length) return null;
  return { brokerage: num(b.brokerage), stt: num(b.stt), exchange: num(b.exchange), sebi: num(b.sebi), stamp: num(b.stamp),
    gst: num(b.gst), slippage: num(b.slippage), total: num(b.total) };
}

/** "brokerage ₹40.00 · STT ₹2.10 · exchange ₹0.06 · SEBI ₹0.00 · stamp ₹0.15 · GST ₹7.22 · slippage ₹1.05" under the desk
 *  cost card; "brokerage ₹40.00 · slippage ₹1.95" for a trade priced with the flat model, which has no statutory charges
 *  (showing them as ₹0.00 would read as if they had been charged at zero). */
export function costsBreakdownText(b: CostsBreakdown | null, inr: (n: number) => string, statutory = true): string | null {
  if (!b) return null;
  const parts: Array<[string, number | null]> = statutory
    ? [["brokerage", b.brokerage], ["STT", b.stt], ["exchange", b.exchange], ["SEBI", b.sebi], ["stamp", b.stamp], ["GST", b.gst], ["slippage", b.slippage]]
    : [["brokerage", b.brokerage], ["slippage", b.slippage]];
  const known = parts.filter(([, n]) => n != null) as Array<[string, number]>;
  return known.length ? known.map(([k, n]) => `${k} ${inr(n)}`).join(" · ") : null;
}

export interface PaperTrade {
  id: string;
  symbol: string;
  quantity: number | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  note: string | null;
  /** Where the plan came from (`source.kind`, e.g. "scanner"), with its bucket and signal date when sent. */
  source: { kind: string | null; bucket: string | null; signalDate: string | null } | null;
  openedAt: string | null;
  status: "open" | "closed";
  closedAt: string | null;
  exitPrice: number | null;
  exitReason: ExitReason | null;
  /** The exit reason exactly as sent (lower case): differs from `exitReason` only for a code this screen does not know. */
  exitReasonCode: string | null;
  /** The session the trade was closed on, and the route's note on it (e.g. both levels in one session). */
  exitSession: string | null;
  exitNote: string | null;
  /** Why an open trade has no mark ("no_prices_for_symbol", "prices_unavailable"). */
  markError: string | null;
  /** The last end-of-day close the trade was marked at, and its session. */
  lastClose: number | null;
  lastCloseDate: string | null;
  unrealizedRs: number | null;
  realizedRs: number | null;
  // ── PRD §13.4 field set (null when the route did not send it or the trade predates it) ──
  entryRule: EntryRule;
  entryWindowSessions: number | null;
  maxHoldSessions: number | null;
  signalAt: string | null;
  strategyVersion: string | null;
  rationale: string | null;
  rulesVersion: string | null;
  costModel: CostModel | null;
  /** Estimated round-trip costs at the target and at the stop, ₹. */
  estCostsAtTarget: number | null;
  estCostsAtStop: number | null;
  entryStatus: EntryStatus | null;
  entrySession: string | null;
  simEntryPrice: number | null;
  /** Eligible sessions read since the trade was recorded, and sessions held. */
  observations: number | null;
  heldSessions: number | null;
  mfePct: number | null;
  maePct: number | null;
  mfeRs: number | null;
  maeRs: number | null;
  /** Gross P&L (unrealised while open), estimated costs and net P&L, ₹. */
  grossRs: number | null;
  costsRs: number | null;
  /** The costs above by component (brokerage, STT, exchange, SEBI, stamp, GST, slippage). */
  costsBreakdown: CostsBreakdown | null;
  costsBasis: string | null;
  netRs: number | null;
  flags: PaperFlag[];
  // ── exits (exit-rules-v1): opt-in research rules, the versioned stop history, the stop in force ──
  exitRules: ExitRuleLabel[];
  exitRulesVersion: string | null;
  stopHistory: StopVersion[];
  /** The stop in force for the next session (open) or at the exit (closed); null when the route did not send it. */
  currentStop: number | null;
  stopVersion: number | null;
}

// ── strategy paper trades (kind "strategy": futures and option structures, rules desk-paper-v3) ──

export type StrategyExitReason = ExitReason | "expiry" | "roll";
/** The premium levels stored on a strategy trade at entry (services/strategy_levels.py), per unit of the position's lot
 *  multiple; the whole structure is evaluated against them on its end-of-day marks. */
export interface PremiumPlan {
  kind: "debit" | "credit" | null;
  entryPerUnit: number | null;
  stopPerUnit: number | null;
  t1PerUnit: number | null;
  t2PerUnit: number | null;
  unitShares: number | null;
  version: string | null;
  source: string | null;
}
function readPremiumPlan(v: unknown): PremiumPlan | null {
  const p = rec(v);
  if (!Object.keys(p).length) return null;
  const kind = str(p.kind);
  return {
    kind: kind === "debit" || kind === "credit" ? kind : null,
    entryPerUnit: num(p.entry_per_unit), stopPerUnit: num(p.stop_per_unit), t1PerUnit: num(p.t1_per_unit), t2PerUnit: num(p.t2_per_unit),
    unitShares: num(p.unit_shares), version: str(p.version), source: str(p.source),
  };
}
const STRATEGY_EXIT_REASONS: readonly string[] = [...EXIT_REASONS, "expiry", "roll"];
export type StrategyDirection = "bullish" | "bearish" | "neutral";
const DIRECTIONS: readonly string[] = ["bullish", "bearish", "neutral"];
export type LegKind = "future" | "option" | "cash";
const LEG_KINDS: readonly string[] = ["future", "option", "cash"];
export type MarkBasis = "settle" | "close" | "expiry_intrinsic" | "final_settle" | "underlying_close";
const MARK_BASES: readonly string[] = ["settle", "close", "expiry_intrinsic", "final_settle", "underlying_close"];

/** One contract leg: what was recorded at entry (never edited) and where it is marked now. */
export interface StrategyLeg {
  index: number;
  kind: LegKind;
  side: "buy" | "sell";
  /** Lots for a future or option; shares for a cash leg. */
  lots: number;
  lotSize: number;
  entry: number | null;
  expiry: string | null;
  strike: number | null;
  optionType: "call" | "put" | null;
  priceSource: string | null;
  /** The route's one-line name for the leg ("Buy 1 lot call 1300 27 Oct"). */
  label: string;
  mark: number | null;
  markDate: string | null;
  markBasis: MarkBasis | null;
  markBasisText: string | null;
  markSource: string | null;
  /** (mark − entry) × lots × lot size × side, ₹; null while the leg has no mark. */
  pnlRs: number | null;
}

/** The signal the trade was opened from: saved with the trade and never changed. */
export interface StrategySignal {
  signalAt: string | null;
  ruleVersion: string | null;
  modelVersion: string | null;
  sourceRefs: Array<{ kind: string; ref: string; asOf: string | null }>;
  evidenceSummary: string | null;
}

export interface LifecycleEvent {
  type: string;
  at: string | null;
  session: string | null;
  reason: string | null;
  text: string;
}

export interface StrategyFlag extends PaperFlag {
  /** The leg the flag is about (0-based), null for the whole trade. */
  leg: number | null;
}

export interface StrategyPaperTrade {
  id: string;
  kind: "strategy";
  underlying: string;
  direction: StrategyDirection | null;
  family: string | null;
  familyName: string | null;
  /** "Bull call spread 1300/1360 · 27 Oct · 2 lots", from the route. */
  summaryText: string;
  strategyPlanId: string | null;
  /** Phase 2.2: the lifecycle state (POSITION_OPEN, CLOSED, ...), the TradePlan the trade cites, and a roll's links. */
  state: string | null;
  tradePlanId: string | null;
  rolledTo: string | null;
  rolledFrom: string | null;
  referencePrice: number | null;
  stopUnderlying: number | null;
  targetUnderlying: number | null;
  note: string | null;
  openedAt: string | null;
  status: "open" | "closed";
  closedAt: string | null;
  exitReason: StrategyExitReason | null;
  exitReasonCode: string | null;
  exitSession: string | null;
  exitNote: string | null;
  /** Which levels fired the stop or target: the underlying's, or the structure's premium levels. */
  exitBasis: "underlying" | "premium" | null;
  premiumPlan: PremiumPlan | null;
  /** The structure's value per unit at the latest marks (debit: what it would sell for; credit: the buy-back cost). */
  structureValuePerUnit: number | null;
  maxHoldSessions: number | null;
  rulesVersion: string | null;
  costModel: CostModel | null;
  /** Futures losses can exceed margin: the route's words, null for an option-only structure. */
  riskNote: string | null;
  signal: StrategySignal;
  /** The fingerprint of the signal and legs saved at entry, and whether the stored record still matches it. */
  entryRecordHash: string | null;
  entryRecordIntact: boolean | null;
  legs: StrategyLeg[];
  /** Premium the option legs paid (negative) or received (positive) at entry, and at the marks, ₹. */
  netPremiumRs: number | null;
  markPremiumRs: number | null;
  grossRs: number | null;
  costsRs: number | null;
  /** The costs above by component (brokerage, STT, exchange, SEBI, stamp, GST, slippage). */
  costsBreakdown: CostsBreakdown | null;
  costsBasis: string | null;
  netRs: number | null;
  unrealizedRs: number | null;
  realizedRs: number | null;
  mfeRs: number | null;
  maeRs: number | null;
  observations: number | null;
  heldSessions: number | null;
  checkedThrough: string | null;
  lastMarkDate: string | null;
  markError: string | null;
  flags: StrategyFlag[];
  events: LifecycleEvent[];
}

export interface PaperSummary {
  open: number | null;
  closed: number | null;
  wins: number | null;
  losses: number | null;
  realizedRs: number | null;
  unrealizedRs: number | null;
  /** Open trades without a mark (then the unrealised total is not given). */
  unmarkedOpen: number | null;
  /** More closed trades are on record than were listed. */
  partial: boolean;
  netRealizedRs: number | null;
  costsRealizedRs: number | null;
  netUnrealizedRs: number | null;
  /** Open trades whose entry level has not traded yet. */
  entryPending: number | null;
  /** Closed without a position: the entry was not reached, or it was cancelled. */
  notEntered: number | null;
}

export interface PaperBook {
  asOf: string | null;
  checkedThrough: string | null;
  /** The price source and basis as the route names them. */
  source: string | null;
  priceBasis: string | null;
  /** "prices_unavailable" | "prices_partially_unavailable" when marks could not all be read. */
  marksError: string | null;
  exitRule: string | null;
  trades: PaperTrade[];
  /** Futures and option strategies, listed beside the share trades (`trades` holds share trades only). */
  strategyTrades: StrategyPaperTrade[];
  summary: PaperSummary | null;
  /** entry rule → the route's sentence for it. */
  entryRules: Partial<Record<EntryRule, string>>;
  rulesVersion: string | null;
  costModel: CostModel | null;
  /** The route's own statement that paper trades never create a broker order. */
  orders: string | null;
}

function readCostModel(v: unknown): CostModel | null {
  const m = rec(v);
  if (!Object.keys(m).length) return null;
  return { name: str(m.name), slippagePctPerSide: num(m.slippage_pct_per_side), brokerageRsPerSide: num(m.brokerage_rs_per_side),
    version: str(m.version) };
}

function readTrade(v: unknown): PaperTrade | null {
  const t = rec(v);
  const id = str(t.id);
  const symbol = str(t.symbol)?.toUpperCase();
  const status = str(t.status)?.toLowerCase();
  if (!id || !symbol || (status !== "open" && status !== "closed")) return null;
  const src = rec(t.source);
  const reason = str(t.exit_reason)?.toLowerCase();
  const q = num(t.quantity);
  const rule = str(t.entry_rule);
  const entryStatus = str(t.entry_status);
  const est = rec(t.est_costs_rs);
  return {
    id, symbol, status,
    quantity: q != null && q > 0 ? q : null,
    entry: price(t.entry_price),
    stop: price(t.stop_price),
    target: price(t.target_price),
    note: str(t.note),
    source: Object.keys(src).length ? { kind: str(src.kind), bucket: str(src.bucket), signalDate: str(src.signal_date) } : null,
    openedAt: str(t.opened_at),
    closedAt: str(t.closed_at),
    exitPrice: price(t.exit_price),
    exitReason: reason && EXIT_REASONS.includes(reason) ? (reason as ExitReason) : null,
    exitReasonCode: reason ?? null,
    exitSession: str(t.exit_session),
    exitNote: str(t.exit_note),
    markError: str(t.mark_error),
    lastClose: price(t.last_close),
    lastCloseDate: str(t.last_close_date),
    unrealizedRs: num(t.unrealized_pnl_rs),
    realizedRs: num(t.realized_pnl_rs),
    entryRule: rule && ENTRY_RULES.includes(rule) ? (rule as EntryRule) : "at_once",
    entryWindowSessions: num(t.entry_window_sessions),
    maxHoldSessions: num(t.max_hold_sessions),
    signalAt: str(t.signal_at),
    strategyVersion: str(t.strategy_version),
    rationale: str(t.rationale),
    rulesVersion: str(t.rules_version),
    costModel: readCostModel(t.cost_model),
    estCostsAtTarget: num(est.at_target),
    estCostsAtStop: num(est.at_stop),
    entryStatus: entryStatus && ENTRY_STATUSES.includes(entryStatus) ? (entryStatus as EntryStatus) : null,
    entrySession: str(t.entry_session),
    simEntryPrice: price(t.sim_entry_price),
    observations: num(t.observations),
    heldSessions: num(t.held_sessions),
    mfePct: num(t.mfe_pct),
    maePct: num(t.mae_pct),
    mfeRs: num(t.mfe_rs),
    maeRs: num(t.mae_rs),
    grossRs: num(t.gross_pnl_rs),
    costsRs: num(t.costs_rs),
    costsBreakdown: readCostsBreakdown(t.costs_breakdown),
    costsBasis: str(t.costs_basis),
    netRs: num(t.net_pnl_rs),
    flags: (Array.isArray(t.flags) ? t.flags : []).flatMap((x): PaperFlag[] => {
      const f = rec(x);
      const code = str(f.code);
      const text = str(f.text);
      return code && text ? [{ code, text, session: str(f.session), price: num(f.price) }] : [];
    }),
    exitRules: readExitRules(t.exit_rules),
    exitRulesVersion: str(t.exit_rules_version),
    stopHistory: readStopHistory(t.stop_history),
    currentStop: price(t.current_stop),
    stopVersion: num(t.stop_version),
  };
}

function readFlags(v: unknown): StrategyFlag[] {
  return (Array.isArray(v) ? v : []).flatMap((x): StrategyFlag[] => {
    const f = rec(x);
    const code = str(f.code);
    const text = str(f.text);
    return code && text ? [{ code, text, session: str(f.session), price: num(f.price), leg: num(f.leg) }] : [];
  });
}

/** A strategy row. Unlike a share row, a row of kind "strategy" without its id, legs or signal is a broken contract:
 *  it throws (the screen shows the contract error) instead of dropping a trade the user has on record. */
function readStrategyTrade(v: unknown): StrategyPaperTrade {
  const t = rec(v);
  const id = str(t.id);
  const underlying = str(t.underlying)?.toUpperCase();
  const status = str(t.status)?.toLowerCase();
  const sig = rec(t.signal);
  if (!id || !underlying || (status !== "open" && status !== "closed") || !Array.isArray(t.legs) || !t.legs.length || !Object.keys(sig).length) {
    throw ApiError.contractDrift("desk.paper-trades: a strategy trade without its id, legs or signal");
  }
  const legs = t.legs.map((x): StrategyLeg => {
    const l = rec(x);
    const side = str(l.side);
    const kind = str(l.kind);
    const basis = str(l.mark_basis);
    const lots = num(l.lots);
    const lotSize = num(l.lot_size);
    if ((side !== "buy" && side !== "sell") || !kind || !LEG_KINDS.includes(kind) || lots == null || lotSize == null) {
      throw ApiError.contractDrift("desk.paper-trades: a strategy leg without its side, kind, lots or lot size");
    }
    const type = str(l.option_type);
    return {
      index: num(l.index) ?? 0, kind: kind as LegKind, side, lots, lotSize,
      entry: price(l.entry_price), expiry: str(l.expiry), strike: price(l.strike),
      optionType: type === "call" || type === "put" ? type : null,
      priceSource: str(l.price_source), label: str(l.label) ?? kind,
      mark: price(l.mark), markDate: str(l.mark_date),
      markBasis: basis && MARK_BASES.includes(basis) ? (basis as MarkBasis) : null,
      markBasisText: str(l.mark_basis_text), markSource: str(l.mark_source), pnlRs: num(l.pnl_rs),
    };
  });
  const reason = str(t.exit_reason)?.toLowerCase();
  const direction = str(t.direction);
  const refs = (Array.isArray(sig.source_refs) ? sig.source_refs : []).flatMap((x) => {
    const r = rec(x);
    const kind = str(r.kind);
    const ref = str(r.ref);
    return kind && ref ? [{ kind, ref, asOf: str(r.as_of) }] : [];
  });
  const risk = rec(t.risk);
  return {
    id, kind: "strategy", underlying, status,
    direction: direction && DIRECTIONS.includes(direction) ? (direction as StrategyDirection) : null,
    family: str(t.family), familyName: str(t.family_name),
    summaryText: str(t.summary_text) ?? `${underlying} strategy`,
    strategyPlanId: str(t.strategy_plan_id),
    state: str(t.state),
    tradePlanId: str(rec(t.plan_ref).plan_id),
    rolledTo: str(t.rolled_to),
    rolledFrom: str(rec(t.rolled_from).trade_id),
    referencePrice: price(t.reference_price), stopUnderlying: price(t.stop_underlying), targetUnderlying: price(t.target_underlying),
    note: str(t.note), openedAt: str(t.opened_at), closedAt: str(t.closed_at),
    exitReason: reason && STRATEGY_EXIT_REASONS.includes(reason) ? (reason as StrategyExitReason) : null,
    exitReasonCode: reason ?? null,
    exitSession: str(t.exit_session), exitNote: str(t.exit_note), maxHoldSessions: num(t.max_hold_sessions),
    exitBasis: str(t.exit_basis) === "premium" ? "premium" : str(t.exit_basis) === "underlying" ? "underlying" : null,
    premiumPlan: readPremiumPlan(t.premium_plan),
    structureValuePerUnit: num(t.structure_value_per_unit),
    rulesVersion: str(t.rules_version), costModel: readCostModel(t.cost_model), riskNote: str(risk.note),
    signal: { signalAt: str(sig.signal_at), ruleVersion: str(sig.rule_version), modelVersion: str(sig.model_version), sourceRefs: refs, evidenceSummary: str(sig.evidence_summary) },
    entryRecordHash: str(t.entry_record_hash), entryRecordIntact: typeof t.entry_record_intact === "boolean" ? t.entry_record_intact : null,
    legs,
    netPremiumRs: num(t.net_premium_rs), markPremiumRs: num(t.mark_premium_rs),
    grossRs: num(t.gross_pnl_rs), costsRs: num(t.costs_rs), costsBreakdown: readCostsBreakdown(t.costs_breakdown), costsBasis: str(t.costs_basis), netRs: num(t.net_pnl_rs),
    unrealizedRs: num(t.unrealized_pnl_rs), realizedRs: num(t.realized_pnl_rs),
    mfeRs: num(t.mfe_rs), maeRs: num(t.mae_rs), observations: num(t.observations), heldSessions: num(t.held_sessions),
    checkedThrough: str(t.checked_through), lastMarkDate: str(t.last_mark_date), markError: str(t.mark_error),
    flags: readFlags(t.flags),
    events: (Array.isArray(t.events) ? t.events : []).flatMap((x): LifecycleEvent[] => {
      const e = rec(x);
      const type = str(e.type);
      const text = str(e.text);
      return type && text ? [{ type, at: str(e.at), session: str(e.session), reason: str(e.reason), text }] : [];
    }),
  };
}

async function fetchPaperBook(signal?: AbortSignal): Promise<PaperBook> {
  const res = await http({ path: "/api/desk/paper-trades", query: { status: "all" }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.trades)) throw ApiError.contractDrift("desk.paper-trades: no trades list");
  const isStrategy = (v: unknown) => rec(v).kind === "strategy";
  const trades = d.trades.filter((v) => !isStrategy(v)).flatMap((v) => {
    const t = readTrade(v);
    return t ? [t] : [];
  });
  const strategyTrades = d.trades.filter(isStrategy).map(readStrategyTrade);
  const s = rec(d.summary);
  const summary: PaperSummary | null = Object.keys(s).length
    ? {
        open: num(s.open), closed: num(s.closed), wins: num(s.wins), losses: num(s.losses),
        realizedRs: num(s.realized_pnl_rs), unrealizedRs: num(s.unrealized_pnl_rs), unmarkedOpen: num(s.unmarked_open), partial: s.partial === true,
        netRealizedRs: num(s.net_realized_pnl_rs), costsRealizedRs: num(s.costs_realized_rs), netUnrealizedRs: num(s.net_unrealized_pnl_rs),
        entryPending: num(s.entry_pending), notEntered: num(s.not_entered),
      }
    : null;
  const rules = rec(d.entry_rules);
  const entryRules: Partial<Record<EntryRule, string>> = {};
  for (const r of ENTRY_RULES) {
    const text = str(rules[r]);
    if (text) entryRules[r as EntryRule] = text;
  }
  return {
    asOf: str(d.as_of), checkedThrough: str(d.checked_through), source: str(d.source), priceBasis: str(d.price_basis),
    marksError: str(d.marks_error), exitRule: str(d.exit_rule), trades, strategyTrades, summary,
    entryRules, rulesVersion: str(d.rules_version), costModel: readCostModel(d.cost_model), orders: str(d.orders),
  };
}

export function usePaperTrades() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<PaperBook>({
    queryKey: [...PAPER_KEY, profile ?? "self"],
    staleTime: 60_000,
    retry,
    queryFn: ({ signal }) => fetchPaperBook(signal),
  });
}

/** POST /api/desk/paper-trades — the body exactly as the route takes it. */
export interface NewPaperTrade {
  symbol: string;
  quantity: number;
  entry_price: number;
  stop_price: number;
  target_price: number | null;
  source: { kind: "scanner" | "strategy_plan"; bucket?: string; signal_date?: string };
  /** PRD §13.4, all optional: how the entry fills, how long it waits, the most sessions to hold, when the signal was
   *  generated, the strategy's version and why. */
  entry_rule?: EntryRule;
  entry_window_sessions?: number;
  max_hold_sessions?: number;
  signal_at?: string;
  strategy_version?: string;
  rationale?: string;
  /** Phase 2.1: the TradePlan whose levels these are; the route refuses levels that are not the plan's. */
  plan_ref?: PlanRef;
}

/** The `Idempotency-Key` header the paper-trade route takes (backend/routes/desk_trading.py). */
export const IDEMPOTENCY_HEADER = "Idempotency-Key";

/**
 * One idempotency key per submission. Sending the same body again after a failure (a timeout whose request may have
 * reached the server, a refused write the user retries) reuses the key, so the route answers with the trade the
 * first attempt made instead of recording a second one; a different body, or the next submission after a success,
 * gets a fresh key.
 */
export function useSubmissionKey() {
  const last = useRef<{ body: string; key: string } | null>(null);
  return useRef({
    keyFor(body: unknown): string {
      const text = JSON.stringify(body);
      if (!last.current || last.current.body !== text) last.current = { body: text, key: correlationId() };
      return last.current.key;
    },
    done(): void {
      last.current = null;
    },
  }).current;
}

export function useAddPaperTrade() {
  const qc = useQueryClient();
  const submission = useSubmissionKey();
  return useMutation({
    mutationFn: async (body: NewPaperTrade): Promise<PaperTrade | null> => {
      const headers = { [IDEMPOTENCY_HEADER]: submission.keyFor(body) };
      const res = await http({ method: "POST", path: "/api/desk/paper-trades", body, headers, noRetry: true });
      // The trade is created once the route answers 2xx (201, or 200 for a replayed key); its echo is only used for the id.
      return readTrade(rec(res.data).trade);
    },
    onSuccess: () => {
      submission.done();
      return qc.invalidateQueries({ queryKey: PAPER_KEY });
    },
  });
}

/** POST /api/desk/paper-trades with kind "strategy" — the body exactly as the route takes it (PRD §17.6). Nothing
 *  places an order: this records a simulated trade. The signal and the legs are saved as sent and never edited. */
export interface NewStrategyLeg {
  kind: LegKind;
  side: "buy" | "sell";
  /** Lots for a future or option; shares for a cash leg (lot_size 1). */
  lots: number;
  lot_size: number;
  /** Per unit; an option's premium. */
  entry_price: number;
  /** YYYY-MM-DD; null for a cash leg. */
  expiry: string | null;
  strike: number | null;
  option_type: "call" | "put" | null;
  /** Where the entry price came from, e.g. "NSE F&O bhavcopy close, 2026-10-19" (required). */
  price_source: string;
}

export interface NewStrategyPaperTrade {
  kind: "strategy";
  underlying: string;
  direction: StrategyDirection;
  /** A key of the route's `strategy_families` list (bull_call_spread, iron_condor, long_future, custom ...). */
  family: string;
  strategy_plan_id?: string;
  /** The underlying's last close when the plan was made. */
  reference_price: number;
  /** The underlying levels that invalidate / fulfil the plan, on the loss / profit side of the reference; none for neutral. */
  stop_underlying?: number | null;
  target_underlying?: number | null;
  /** 1 to 4 legs; defined-risk structures and a plain futures leg only. */
  legs: NewStrategyLeg[];
  signal: {
    signal_at: string;
    rule_version: string;
    model_version?: string | null;
    source_refs?: Array<{ kind: string; ref: string; as_of?: string | null }>;
    evidence_summary: string;
  };
  max_hold_sessions?: number;
  note?: string;
  plan_ref?: PlanRef;
}

export function useAddStrategyPaperTrade() {
  const qc = useQueryClient();
  const submission = useSubmissionKey();
  return useMutation({
    mutationFn: async (body: NewStrategyPaperTrade): Promise<StrategyPaperTrade> => {
      const headers = { [IDEMPOTENCY_HEADER]: submission.keyFor(body) };
      const res = await http({ method: "POST", path: "/api/desk/paper-trades", body, headers, noRetry: true });
      return readStrategyTrade(rec(res.data).trade);
    },
    onSuccess: () => {
      submission.done();
      return qc.invalidateQueries({ queryKey: PAPER_KEY });
    },
  });
}

export function useClosePaperTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await http({ method: "POST", path: `/api/desk/paper-trades/${encodeURIComponent(id)}/close`, body: {}, noRetry: true });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: PAPER_KEY }),
  });
}

// ── alerts (PRD §6.7): price, filings, categories, volume, scanner, sector, risk ──

/** Every condition the route takes (backend/services/desk_alerts.py). */
export type AlertCondition = "above" | "below" | "filing" | "category" | "volume" | "scanner" | "sector" | "risk";
const CONDITIONS: readonly AlertCondition[] = ["above", "below", "filing", "category", "volume", "scanner", "sector", "risk"];

/** A price alert (above / below a level): the shape the Portfolio and Chart tabs use. */
export interface DeskAlert {
  id: string;
  symbol: string;
  condition: "above" | "below";
  level: number | null;
  note: string | null;
  createdAt: string | null;
  status: "active" | "fired";
  firedAt: string | null;
  /** The session whose high (above) or low (below) reached the level. */
  firedSession: string | null;
  firedPrice: number | null;
  /** An active alert's last end-of-day close, or why there is none. */
  lastClose: number | null;
  lastCloseDate: string | null;
  markError: string | null;
  /** Why it fired, in the route's words (null while active). */
  reason: string | null;
}

/** Any alert, whatever its condition (the Market intelligence list). */
export interface AnyAlert {
  id: string;
  /** null for an alert on every company (a category) or on a sector index. */
  symbol: string | null;
  condition: AlertCondition;
  level: number | null;
  /** The condition's settings as stored: impact, category, multiple, stage, index, threshold_pct, direction. */
  params: Record<string, string | number | null>;
  /** The alert in one plain line, from the route ("RELIANCE: a new exchange filing"). */
  label: string | null;
  /** The rule it is checked by, from the route. */
  rule: string | null;
  note: string | null;
  createdAt: string | null;
  status: "active" | "fired";
  firedAt: string | null;
  firedSession: string | null;
  firedPrice: number | null;
  /** Why it fired, and what it fired on (a filing's id and link, a session's volume…). */
  reason: string | null;
  evidence: Record<string, unknown> | null;
  /** A source this alert reads could not be read on the last check (it stays active, unchecked). */
  checkError: string | null;
  checkedThrough: string | null;
}

export interface AlertBook {
  asOf: string | null;
  /** The last session the alerts were checked against. */
  checkedThrough: string | null;
  source: string | null;
  marksError: string | null;
  firingRule: string | null;
  /** Price alerts only (above / below). */
  alerts: DeskAlert[];
  /** Every alert, every condition, newest first as the route sends them. */
  all: AnyAlert[];
  /** Codes of the sources that could not be read on this check. */
  checkErrors: string[];
  /** How and when alerts are checked, and where they show (in-app), in the route's words. */
  checkNote: string | null;
  delivery: string | null;
  conditions: Array<{ condition: AlertCondition; rule: string }>;
}

const isCondition = (v: string | null | undefined): v is AlertCondition => !!v && (CONDITIONS as readonly string[]).includes(v);

function readAny(v: unknown): AnyAlert | null {
  const a = rec(v);
  const id = str(a.id);
  const condition = str(a.condition)?.toLowerCase() ?? null;
  const status = str(a.status)?.toLowerCase();
  if (!id || !isCondition(condition) || (status !== "active" && status !== "fired")) return null;
  const params: Record<string, string | number | null> = {};
  for (const [k, val] of Object.entries(rec(a.params))) {
    if (typeof val === "string" || (typeof val === "number" && Number.isFinite(val)) || val === null) params[k] = val;
  }
  const ev = rec(a.evidence);
  return {
    id, condition, status,
    symbol: str(a.symbol)?.toUpperCase() ?? null,
    level: num(a.level),
    params,
    label: str(a.label),
    rule: str(a.rule),
    note: str(a.note),
    createdAt: str(a.created_at),
    firedAt: str(a.fired_at),
    firedSession: str(a.fired_session),
    firedPrice: price(a.fired_price),
    reason: str(a.reason),
    evidence: Object.keys(ev).length ? ev : null,
    checkError: str(a.check_error),
    checkedThrough: str(a.checked_through),
  };
}

function readAlert(v: unknown): DeskAlert | null {
  const a = rec(v);
  const id = str(a.id);
  const symbol = str(a.symbol)?.toUpperCase();
  const condition = str(a.condition)?.toLowerCase();
  const status = str(a.status)?.toLowerCase();
  if (!id || !symbol || (condition !== "above" && condition !== "below") || (status !== "active" && status !== "fired")) return null;
  return {
    id, symbol, condition, status,
    level: price(a.level),
    note: str(a.note),
    createdAt: str(a.created_at),
    firedAt: str(a.fired_at),
    firedSession: str(a.fired_session),
    firedPrice: price(a.fired_price),
    lastClose: price(a.last_close),
    lastCloseDate: str(a.last_close_date),
    markError: str(a.mark_error),
    reason: str(a.reason),
  };
}

async function fetchAlerts(signal?: AbortSignal): Promise<AlertBook> {
  const res = await http({ path: "/api/desk/alerts", query: { status: "all" }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.alerts)) throw ApiError.contractDrift("desk.alerts: no alerts list");
  const alerts = d.alerts.flatMap((v) => {
    const a = readAlert(v);
    return a ? [a] : [];
  });
  const all = d.alerts.flatMap((v) => {
    const a = readAny(v);
    return a ? [a] : [];
  });
  const conditions = (Array.isArray(d.conditions) ? d.conditions : []).flatMap((v): AlertBook["conditions"] => {
    const c = rec(v);
    const k = str(c.condition);
    return isCondition(k) ? [{ condition: k, rule: str(c.rule) ?? "" }] : [];
  });
  return {
    asOf: str(d.as_of), checkedThrough: str(d.checked_through), source: str(d.source), marksError: str(d.marks_error),
    firingRule: str(d.firing_rule), alerts, all,
    checkErrors: (Array.isArray(d.check_errors) ? d.check_errors : []).flatMap((v) => (str(v) ? [str(v) as string] : [])),
    checkNote: str(d.check_note), delivery: str(d.delivery), conditions,
  };
}

export function useDeskAlerts() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<AlertBook>({
    queryKey: [...ALERTS_KEY, profile ?? "self"],
    staleTime: 60_000,
    retry,
    queryFn: ({ signal }) => fetchAlerts(signal),
  });
}

/** POST /api/desk/alerts — a price alert, the body exactly as the route takes it. */
export interface NewAlert {
  symbol: string;
  condition: "above" | "below";
  level: number;
}

/** POST /api/desk/alerts — any condition, the body exactly as the route takes it. */
export type NewDeskAlert =
  | NewAlert
  | { condition: "filing"; symbol: string; impact?: "any" | "high" }
  | { condition: "category"; category: string; symbol?: string }
  | { condition: "volume"; symbol: string; multiple: number }
  | { condition: "scanner"; symbol: string; stage?: string }
  | { condition: "sector"; index: string; threshold_pct: number; direction?: "up" | "down" | "either" }
  | { condition: "risk"; symbol: string; level: number };

export function useAddAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: NewAlert): Promise<DeskAlert | null> => {
      const res = await http({ method: "POST", path: "/api/desk/alerts", body, noRetry: true });
      return readAlert(rec(res.data).alert);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
  });
}

/** Any condition; the answer's alert is read whatever its kind. */
export function useCreateAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: NewDeskAlert): Promise<AnyAlert | null> => {
      const res = await http({ method: "POST", path: "/api/desk/alerts", body, noRetry: true });
      return readAny(rec(res.data).alert);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
  });
}

export function useDeleteAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await http({ method: "DELETE", path: `/api/desk/alerts/${encodeURIComponent(id)}`, noRetry: true });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
  });
}

// ── per-trade figures the Portfolio tab shows (worked out from the trade) ─

const IST = "Asia/Kolkata";
const istDay = (iso: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? d.toLocaleDateString("en-CA", { timeZone: IST }) : null;
};

/** True when the trade was opened today, India time. */
export function openedToday(t: PaperTrade, now: Date = new Date()): boolean {
  return istDay(t.openedAt) === now.toLocaleDateString("en-CA", { timeZone: IST });
}

/** Calendar days from opening to closing (India time); null without both stamps. */
export function heldDays(t: PaperTrade): number | null {
  const a = istDay(t.openedAt);
  const b = istDay(t.closedAt);
  if (!a || !b) return null;
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

/** A closed trade's return on its entry, percent: (exit − entry) ÷ entry. */
export function tradeReturnPct(t: PaperTrade): number | null {
  if (t.exitPrice == null || t.entry == null) return null;
  return ((t.exitPrice - t.entry) / t.entry) * 100;
}

/** A closed trade's result in R: (exit − entry) ÷ (entry − stop); null without a stop below the entry. */
export function tradeR(t: PaperTrade): number | null {
  if (t.exitPrice == null || t.entry == null || t.stop == null || !(t.entry > t.stop)) return null;
  return (t.exitPrice - t.entry) / (t.entry - t.stop);
}


// ── F&O roll (backend services/fno_roll.py; GET / POST /api/desk/paper-trades/{id}/roll) ──────────────────────────
export interface RollLegView { label: string; price: number | null; strike: number | null; expiry: string | null }
export interface RollPreview {
  eligible: boolean;
  /** Why it cannot roll, in the route's words (e.g. roll_chain_not_ready before the 22:15 IST F&O bhavcopy). */
  refusal: { code: string; message: string } | null;
  session: string | null;
  priceSource: string | null;
  strikeShift: number | null;
  oldLegs: RollLegView[];
  newLegs: RollLegView[];
  newExpiry: string | null;
  oldGrossRs: number | null;
  oldNetRs: number | null;
  newCostsRs: number | null;
  newNetPremiumRs: number | null;
  notes: string[];
}

function readRollPreview(v: unknown): RollPreview {
  const d = rec(v);
  const p = rec(d.preview);
  const refusal = rec(d.refusal);
  const legs = (xs: unknown, priceKey: string): RollLegView[] => (Array.isArray(xs) ? xs : []).map((x) => {
    const l = rec(x);
    return { label: str(l.label) ?? "—", price: num(l[priceKey]), strike: num(l.strike), expiry: str(l.expiry) };
  });
  const costs = rec(p.costs);
  return {
    eligible: d.eligible === true,
    refusal: d.eligible === true ? null : { code: str(refusal.code) ?? "roll_refused", message: str(refusal.message) ?? "This trade cannot be rolled." },
    session: str(p.session), priceSource: str(p.price_source), strikeShift: num(p.strike_shift),
    oldLegs: legs(rec(p.old).legs, "close"), newLegs: legs(rec(p.new).legs, "entry_price"), newExpiry: str(rec(p.new).expiry),
    oldGrossRs: num(rec(p.old).gross_pnl_rs), oldNetRs: num(costs.old_net_pnl_rs),
    newCostsRs: num(rec(costs.new_round_trip_estimate).total), newNetPremiumRs: num(rec(p.new).net_premium_rs),
    notes: (Array.isArray(p.notes) ? p.notes : []).map(String),
  };
}

/** The roll preview for one open strategy trade (read only; nothing is written). Loaded only while `id` is set. */
export function useRollPreview(id: string | null) {
  return useQuery({
    queryKey: [...PAPER_KEY, "roll", id],
    enabled: !!id,
    staleTime: 30_000,
    queryFn: async () => readRollPreview((await http({ method: "GET", path: `/api/desk/paper-trades/${encodeURIComponent(id as string)}/roll` })).data),
  });
}

/** POST the roll. One Idempotency-Key per confirmation; the route also answers a repeat with the same pair. */
export function useRollTrade() {
  const qc = useQueryClient();
  const submission = useSubmissionKey();
  return useMutation({
    mutationFn: async (id: string): Promise<{ newId: string | null; replayed: boolean }> => {
      const body = {};
      const headers = { [IDEMPOTENCY_HEADER]: submission.keyFor({ roll: id }) };
      const res = await http({ method: "POST", path: `/api/desk/paper-trades/${encodeURIComponent(id)}/roll`, body, headers, noRetry: true });
      const d = rec(res.data);
      return { newId: str(rec(d.new).id), replayed: d.replayed === true };
    },
    onSuccess: () => {
      submission.done();
      return qc.invalidateQueries({ queryKey: PAPER_KEY });
    },
  });
}
