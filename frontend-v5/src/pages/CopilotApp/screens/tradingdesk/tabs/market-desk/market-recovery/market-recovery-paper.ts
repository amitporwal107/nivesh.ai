/**
 * Market Desk › Market Recovery — part 6, paper trades (live) (contract: docs/market_recovery/DESIGN.md §10; backend
 * services/market_recovery/paper_plan.py and paper_live.py; owner, 4 Nov 2026: paper-trade the top 10 leading-sector candidates
 * at live prices with live exits, the best structure per stock by reward : risk after costs, sized by the risk gate).
 *
 *   GET  /api/market-recovery/paper-plan          per candidate: the chosen structure (or why none), the alternatives with why
 *                                                 each lost or was refused, an open trade already held, the exact desk body
 *                                                 and its Idempotency-Key; the market's live state and the paper capital
 *   POST /api/desk/paper-trades                   the DESK's own paper engine (risk gate, idempotency, duplicates, funds): each
 *                                                 chosen body, sent as is, with the plan's Idempotency-Key — 201 {trade, risk},
 *                                                 or a 409 / 422 refusal whose words writeProblem() gives
 *   GET  /api/market-recovery/paper-trades/live   the user's Market Recovery paper trades (open, and closed today) at live
 *                                                 marks, after the live closes; polled every 30 s while quotes are live
 *
 * Every field is parsed defensively: a missing number is null (shown as "—"), never 0. Nothing is computed here: every figure is
 * the server's. Nothing here places an order: these are simulated trades in the user's paper account.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "../../../desk-data";
import { IDEMPOTENCY_HEADER, PAPER_KEY, writeProblem } from "../../../desk-trading";
import { MR_PATH } from "./market-recovery-data";

export const PAPER_PLAN_PATH = `${MR_PATH}/paper-plan`;
export const PAPER_LIVE_PATH = `${MR_PATH}/paper-trades/live`;
export const DESK_PAPER_PATH = "/api/desk/paper-trades";
export const PLAN_KEY = ["copilot", "desk", "market-recovery", "paper-plan"] as const;
export const LIVE_KEY = ["copilot", "desk", "market-recovery", "paper-live"] as const;
export const LIVE_POLL_MS = 30_000;

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const strs = (v: unknown): string[] => arr(v).map(str).filter((s): s is string => s !== null);

// ── types ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Market { live: boolean; source: string | null; why: string | null; asOf: string | null }
export interface Capital { startingCapitalRs: number | null; cashRs: number | null; blockedRs: number | null; availableRs: number | null }
export interface GateReason { code: string | null; message: string | null }
export interface Approved { outcome: string | null; quantity: number | null; lots: number | null; reasons: GateReason[]; estimatedRiskRs: number | null }
/** One leg of a chosen body, as the desk takes it (a shares plan has none: its body is a share trade). */
export interface BodyLeg {
  kind: string;                 // cash | option | future
  side: string;                 // buy | sell
  lots: number | null;          // shares for a cash leg (lot_size 1)
  lotSize: number | null;
  entryPrice: number | null;
  strike: number | null;
  optionType: string | null;    // call | put
  expiry: string | null;
  priceSource: string | null;
}
export interface PlanCandidate {
  key: string;
  label: string;
  rewardRiskNet: number | null;
  maxGainRs: number | null;
  maxLossRs: number | null;
  approved: Approved | null;
  eligible: boolean | null;
  why: string | null;
  pricesSource: string | null;
  pricesAsOf: string | null;
  /** The exact POST /api/desk/paper-trades body, sent as is (null on an alternative that carries none). */
  body: Record<string, unknown> | null;
  idempotencyKey: string | null;
  // the body's own figures, for the summary
  quantity: number | null;
  entryPrice: number | null;
  stopPrice: number | null;
  targetPrice: number | null;
  legs: BodyLeg[];
}
export interface PlanItem {
  rank: number | null;
  symbol: string;
  name: string | null;
  sector: string | null;
  score: number | null;
  chosen: PlanCandidate | null;
  alternatives: PlanCandidate[];
  skippedReason: string | null;
  openTrade: { id: string | null; status: string | null } | null;
}
export interface PaperPlan {
  asOf: string | null;
  listDate: string | null;
  market: Market;
  capital: Capital | null;
  rule: string | null;
  notes: string[];
  items: PlanItem[];
}
export interface LiveLeg { action: string; instrument: string; strike: number | null; expiry: string | null; lots: number | null; lotSize: number | null; entry: number | null; live: number | null; pnlRs: number | null }
export interface LiveExit { reason: string | null; price: number | null; at: string | null; note: string | null }
export interface LiveTrade {
  id: string;
  symbol: string | null;
  kind: string | null;          // shares | strategy
  label: string | null;
  status: string | null;        // open | closed
  openedAt: string | null;
  quantity: number | null;
  lots: number | null;
  entry: number | null;
  live: number | null;
  stop: number | null;
  target: number | null;
  legs: LiveLeg[];
  pnlRs: number | null;
  riskRs: number | null;
  pnlPct: number | null;
  exit: LiveExit | null;
  flags: string[];
}
export interface LiveTotals { openPnlRs: number | null; openPnlComplete: boolean; realisedTodayRs: number | null; openCount: number | null; closedTodayCount: number | null }
export interface PaperLive { asOf: string | null; market: Market; trades: LiveTrade[]; totals: LiveTotals | null; notes: string[] }

// ── parsing ──────────────────────────────────────────────────────────────────────────────────────────────────────────

function parseMarket(v: unknown): Market {
  const m = rec(v);
  return { live: m.live === true, source: str(m.source), why: str(m.why), asOf: str(m.as_of) };
}

function parseLegs(v: unknown): BodyLeg[] {
  return arr(v).map(rec).flatMap((l) => {
    const kind = str(l.kind);
    return kind ? [{
      kind, side: str(l.side) ?? "", lots: num(l.lots), lotSize: num(l.lot_size), entryPrice: num(l.entry_price), strike: num(l.strike),
      optionType: str(l.option_type), expiry: str(l.expiry), priceSource: str(l.price_source),
    }] : [];
  });
}

function parseCandidate(v: unknown): PlanCandidate | null {
  const c = rec(v);
  const key = str(c.key);
  if (!key) return null;
  const a = rec(c.approved);
  const body = Object.keys(rec(c.body)).length ? rec(c.body) : null;
  const b = body ?? {};
  const prices = rec(c.prices);
  return {
    key, label: str(c.label) ?? key.replace(/_/g, " "),
    rewardRiskNet: num(c.reward_risk_net), maxGainRs: num(c.max_gain_rs), maxLossRs: num(c.max_loss_rs),
    approved: Object.keys(a).length ? {
      outcome: str(a.outcome), quantity: num(a.quantity), lots: num(a.lots), estimatedRiskRs: num(a.estimated_risk_rs),
      reasons: arr(a.reasons).map(rec).map((r) => ({ code: str(r.code), message: str(r.message) })),
    } : null,
    eligible: bool(c.eligible), why: str(c.why),
    pricesSource: str(prices.source), pricesAsOf: str(prices.as_of),
    body, idempotencyKey: str(c.idempotency_key),
    quantity: num(b.quantity), entryPrice: num(b.entry_price), stopPrice: num(b.stop_price ?? b.stop_underlying),
    targetPrice: num(b.target_price ?? b.target_underlying), legs: parseLegs(b.legs),
  };
}

export function parsePaperPlan(v: unknown): PaperPlan {
  const d = rec(v);
  const cap = rec(d.capital);
  return {
    asOf: str(d.as_of), listDate: str(d.list_date), market: parseMarket(d.market),
    capital: Object.keys(cap).length
      ? { startingCapitalRs: num(cap.starting_capital_rs), cashRs: num(cap.cash_rs), blockedRs: num(cap.blocked_rs), availableRs: num(cap.available_rs) }
      : null,
    rule: str(d.rule), notes: strs(d.notes),
    items: arr(d.items).map(rec).flatMap((it) => {
      const symbol = str(it.symbol);
      if (!symbol) return [];
      const ot = rec(it.open_trade);
      return [{
        rank: num(it.rank), symbol, name: str(it.name), sector: str(it.sector), score: num(it.score),
        chosen: parseCandidate(it.chosen),
        alternatives: arr(it.alternatives).map(parseCandidate).filter((c): c is PlanCandidate => c !== null),
        skippedReason: str(it.skipped_reason),
        openTrade: Object.keys(ot).length ? { id: str(ot.id), status: str(ot.status) } : null,
      }];
    }),
  };
}

export function parsePaperLive(v: unknown): PaperLive {
  const d = rec(v);
  const t = rec(d.totals);
  return {
    asOf: str(d.as_of), market: parseMarket(d.market), notes: strs(d.notes),
    totals: Object.keys(t).length ? {
      openPnlRs: num(t.open_pnl_rs), openPnlComplete: t.open_pnl_complete !== false, realisedTodayRs: num(t.realised_today_rs),
      openCount: num(t.open_count), closedTodayCount: num(t.closed_today_count),
    } : null,
    trades: arr(d.trades).map(rec).flatMap((x) => {
      const id = str(x.id);
      if (!id) return [];
      const ex = rec(x.exit);
      return [{
        id, symbol: str(x.symbol), kind: str(x.kind), label: str(x.label), status: str(x.status), openedAt: str(x.opened_at),
        quantity: num(x.quantity), lots: num(x.lots), entry: num(x.entry), live: num(x.live), stop: num(x.stop), target: num(x.target),
        legs: arr(x.legs).map(rec).flatMap((l) => {
          const action = str(l.action);
          return action ? [{
            action, instrument: str(l.instrument) ?? "", strike: num(l.strike), expiry: str(l.expiry), lots: num(l.lots),
            lotSize: num(l.lot_size), entry: num(l.entry), live: num(l.live), pnlRs: num(l.pnl_rs),
          }] : [];
        }),
        pnlRs: num(x.pnl_rs), riskRs: num(x.risk_rs), pnlPct: num(x.pnl_pct),
        exit: Object.keys(ex).length ? { reason: str(ex.reason), price: num(ex.price), at: str(ex.at), note: str(ex.note) } : null,
        flags: strs(x.flags),
      }];
    }),
  };
}

// ── reads ────────────────────────────────────────────────────────────────────────────────────────────────────────────

const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export function usePaperPlan(enabled = true) {
  return useQuery<PaperPlan>({
    queryKey: PLAN_KEY,
    enabled,
    queryFn: async ({ signal }) => {
      // The plan prices every candidate's structures at live quotes and runs each through the risk gate (up to a minute).
      const res = await http({ path: PAPER_PLAN_PATH, signal, timeoutMs: 120_000, noRetry: true });
      return parsePaperPlan(res.data);
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: noRetry4xx,
  });
}

export function usePaperLive(enabled = true) {
  return useQuery<PaperLive>({
    queryKey: LIVE_KEY,
    enabled,
    queryFn: async ({ signal }) => {
      const res = await http({ path: PAPER_LIVE_PATH, signal, timeoutMs: 60_000, noRetry: true });
      return parsePaperLive(res.data);
    },
    // Real-time P&L while quotes are live (the read also applies the live closes); no polling outside the session.
    refetchInterval: (q) => (q.state.data?.market.live ? LIVE_POLL_MS : false),
    refetchOnWindowFocus: false,
    retry: noRetry4xx,
  });
}

// ── opening: each chosen body through the desk's own engine, one at a time ──────────────────────────────────────────

export interface OpenResult { symbol: string; ok: boolean; status: number | null; text: string; tradeId: string | null }

/** POST one chosen body to the desk with the plan's Idempotency-Key; the answer in plain words, never thrown. */
export async function openOne(item: PlanItem): Promise<OpenResult> {
  const c = item.chosen;
  if (!c?.body || !c.idempotencyKey) return { symbol: item.symbol, ok: false, status: null, text: "Nothing to open for this stock.", tradeId: null };
  try {
    const res = await http({ method: "POST", path: DESK_PAPER_PATH, body: c.body, headers: { [IDEMPOTENCY_HEADER]: c.idempotencyKey }, noRetry: true });
    const d = rec(res.data);
    const id = str(rec(d.trade).id);
    const replayed = d.replayed === true;
    return { symbol: item.symbol, ok: true, status: res.status, tradeId: id,
             text: replayed ? "Already opened with this plan's key; the existing paper trade was kept." : `Opened as a paper trade${id ? ` (${id})` : ""}.` };
  } catch (e) {
    return { symbol: item.symbol, ok: false, status: e instanceof ApiError ? e.status ?? null : null, text: writeProblem(e), tradeId: null };
  }
}

/** Opens every chosen candidate that has no open trade, sequentially; then refreshes the plan, the live book and the desk's
 *  paper lists. `results` fills as each answer arrives. */
export function useOpenRecoveryTrades() {
  const qc = useQueryClient();
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<Record<string, OpenResult>>({});
  const run = useCallback(async (items: PlanItem[]) => {
    setRunning(true);
    setResults({});
    try {
      for (const it of items) {
        const r = await openOne(it);
        setResults((prev) => ({ ...prev, [it.symbol]: r }));
      }
    } finally {
      setRunning(false);
      await Promise.all([
        qc.invalidateQueries({ queryKey: PLAN_KEY }),
        qc.invalidateQueries({ queryKey: LIVE_KEY }),
        qc.invalidateQueries({ queryKey: PAPER_KEY }),
      ]);
    }
  }, [qc]);
  return { run, running, results };
}

/** Plan items that can be opened now: a chosen structure with a body and key, and no Market Recovery trade already open. */
export const openable = (plan: PaperPlan | undefined): PlanItem[] =>
  (plan?.items ?? []).filter((i) => i.chosen?.body && i.chosen.idempotencyKey && !i.openTrade);
