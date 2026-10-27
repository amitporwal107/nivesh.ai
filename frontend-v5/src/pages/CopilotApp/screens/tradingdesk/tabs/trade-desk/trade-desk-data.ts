/**
 * Trade Desk (tab 02 of the desk redesign, docs/desk_redesign_20261027/PLAN.md step 3) — the reads this tab adds. The paper
 * trades themselves are `usePaperTrades` (../../desk-trading.ts): ONE GET /api/desk/paper-trades per load, shared with the
 * frame's "N open paper trades" line. That route APPLIES EXITS, so nothing here calls it again or polls it.
 *
 *   GET  /api/desk/paper-account                       cash, capital at risk (`blocked_rs`, not margin), starting capital
 *                                                      (backend/routes/desk_trading.py paper_account)     (usePaperAccount)
 *   GET  /api/desk/exit-job-status                     when the evening exit check last ran: ok | running | late | missed,
 *                                                      the session it covered, the route's own sentence    (useExitJobStatus)
 *   POST /api/desk/strategy/payoff                     payoff-v2 of a recorded F&O structure from its STORED legs and entry
 *                                                      premiums: max profit / loss at expiry, the worst loss after costs,
 *                                                      breakevens. A pure calculation, nothing written    (useStructurePayoff)
 *   GET  /api/strategy-builder/strategies              your saved strategies (workspace/strategies.ts useSavedStrategies)
 *   POST /api/strategy-builder/strategies/{id}/backtest   a backtest run with its provenance block           (useBacktestRun)
 *
 * Paper equity is not in /paper-account: it is the risk profile's (`GET /api/risk/profile` live.equity, risk-profile.ts),
 * the same basis the risk service sizes against. Reads trust nothing: a missing figure is null and the screen says
 * "unknown" or "unavailable", never 0. Nothing here places an order.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "../../desk-data";
import type { StrategyPaperTrade } from "../../desk-trading";
import { fetchPayoff } from "../../strategy/usePayoff";
import type { PayoffRequest, PayoffResponse } from "../../strategy/strategy-contract";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

// ── the paper account ────────────────────────────────────────────────────

export interface PaperAccount {
  startingCapitalRs: number | null;
  cashRs: number | null;
  /** Capital at risk against open positions — NOT exchange margin (the route's `blocked_basis` says why). */
  blockedRs: number | null;
  availableRs: number | null;
  blockedBasis: string | null;
  /** False: no account row yet, so the figures are the opening defaults. */
  stored: boolean;
}

export function readPaperAccount(body: unknown): PaperAccount {
  const d = rec(body);
  if (!("cash_rs" in d)) throw ApiError.contractDrift("desk.paper-account: no cash_rs");
  return {
    startingCapitalRs: num(d.starting_capital_rs), cashRs: num(d.cash_rs), blockedRs: num(d.blocked_rs), availableRs: num(d.available_rs),
    blockedBasis: str(d.blocked_basis), stored: d.stored === true,
  };
}

export function usePaperAccount() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<PaperAccount>({
    queryKey: ["copilot", "desk", "paper-account", profile ?? "self"],
    staleTime: 60_000,
    retry,
    queryFn: async ({ signal }) => readPaperAccount((await http({ path: "/api/desk/paper-account", signal, noRetry: true })).data),
  });
}

// ── the evening exit check ───────────────────────────────────────────────

export type ExitJobStatus = "ok" | "running" | "late" | "missed";

export interface ExitJob {
  status: ExitJobStatus;
  /** The admin route's own word (never_run, failed, partial, no_data, …). */
  state: string | null;
  message: string | null;
  /** The session the last successful check covered (YYYY-MM-DD), and when it finished. */
  lastSession: string | null;
  lastFinishedAt: string | null;
  schedule: string | null;
}

const EXIT_STATUSES: readonly string[] = ["ok", "running", "late", "missed"];

export function readExitJob(body: unknown): ExitJob {
  const d = rec(body);
  const status = str(d.status);
  if (!status || !EXIT_STATUSES.includes(status)) throw ApiError.contractDrift("desk.exit-job-status: no known status");
  const last = rec(d.last_checked);
  return {
    status: status as ExitJobStatus, state: str(d.state), message: str(d.message),
    lastSession: str(last.session), lastFinishedAt: str(last.finished_at), schedule: str(d.schedule),
  };
}

export function useExitJobStatus() {
  return useQuery<ExitJob>({
    queryKey: ["copilot", "desk", "exit-job-status"],
    staleTime: 5 * 60_000,
    retry,
    queryFn: async ({ signal }) => readExitJob((await http({ path: "/api/desk/exit-job-status", signal, noRetry: true })).data),
  });
}

// ── a recorded F&O structure's payoff (payoff-v2) ────────────────────────

const IST = "Asia/Kolkata";
export const istDate = (iso: string | null): string | null => {
  if (!iso) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? d.toLocaleDateString("en-CA", { timeZone: IST }) : null;
};

/**
 * The payoff request for a recorded structure: its STORED legs at their entry prices, the underlying's close when it was
 * recorded, and the recording date. Null when a leg lacks what the calculation needs (an option without a strike, a type
 * or an expiry, a leg without an entry price) or the trade has no reference price — then the figures are unavailable.
 */
export function structurePayoffRequest(t: StrategyPaperTrade): PayoffRequest | null {
  if (t.referencePrice == null) return null;
  const legs: PayoffRequest["legs"] = [];
  for (const l of t.legs) {
    if (l.entry == null) return null;
    if (l.kind === "option" && (l.strike == null || l.optionType == null || !l.expiry)) return null;
    legs.push({
      kind: l.kind, side: l.side, quantity: l.lots, lot_size: l.lotSize, entry_price: l.entry,
      expiry: l.expiry, strike: l.strike, option_type: l.optionType, price_source: l.priceSource, underlying: t.underlying,
    });
  }
  const asOf = istDate(t.openedAt);
  return { underlying: t.underlying, reference_price: t.referencePrice, ...(asOf ? { as_of: asOf } : {}), legs };
}

export function useStructurePayoff(t: StrategyPaperTrade) {
  const req = structurePayoffRequest(t);
  return useQuery<PayoffResponse>({
    queryKey: ["copilot", "desk", "trade-desk", "structure-payoff", t.id, req ? JSON.stringify(req) : "none"],
    enabled: req != null,
    staleTime: 30 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
    queryFn: ({ signal }) => fetchPayoff(req as PayoffRequest, signal),
  });
}

/** Calendar days from today (India time) to a YYYY-MM-DD expiry; null without one. Calendar days, not sessions. */
export function calendarDaysTo(expiry: string | null, now: Date = new Date()): number | null {
  if (!expiry || !/^\d{4}-\d{2}-\d{2}$/.test(expiry)) return null;
  const today = now.toLocaleDateString("en-CA", { timeZone: IST });
  return Math.round((Date.parse(`${expiry}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
}

// ── backtest with provenance ─────────────────────────────────────────────

export interface SweepRow { bps: number; netPnlRs: number | null; expectancyRs: number | null; winRate: number | null; totalReturnPct: number | null }

export interface BacktestRun {
  runId: string | null;
  tradeCount: number | null;
  totalReturnPct: number | null;
  winRate: number | null;
  maxDrawdownPct: number | null;
  profitFactor: number | null;
  /** provenance-v1 (backend services/strategy_engine/backtest.py run_provenance). */
  provenance: {
    schema: string | null;
    dataTo: string | null;
    windowLastSession: string | null;
    codeVersion: string | null;
    specSha: string | null;
    exitRulesVersion: string | null;
    costModel: string | null;
    slippagePctPerSide: number | null;
    brokerageRsPerSide: number | null;
    universeBasis: string | null;
    universeWarning: string | null;
    universeRuleVersion: string | null;
    universeRef: string | null;
    entryTiming: string | null;
    notRecorded: string[];
  };
  sweep: { basis: string | null; rows: SweepRow[] } | null;
}

export function readBacktest(body: unknown): BacktestRun {
  const d = rec(body);
  const m = rec(d.metrics);
  if (!Object.keys(m).length) throw ApiError.contractDrift("strategy-builder.backtest: no metrics");
  const p = rec(d.provenance);
  const data = rec(p.data);
  const rule = rec(p.rule_version);
  const cost = rec(p.cost_model);
  const uni = rec(p.universe);
  const uniRule = rec(uni.rule);
  const sw = rec(m.slippage_sweep);
  const byBps = rec(sw.by_bps);
  const rows = Object.entries(byBps).flatMap(([k, v]): SweepRow[] => {
    const bps = Number(k);
    if (!Number.isFinite(bps)) return [];
    const r = rec(v);
    return [{ bps, netPnlRs: num(r.net_pnl_rs), expectancyRs: num(r.expectancy_rs), winRate: num(r.win_rate), totalReturnPct: num(r.total_return_pct) }];
  }).sort((a, b) => a.bps - b.bps);
  return {
    runId: str(d.run_id),
    tradeCount: num(m.trade_count) ?? num(d.trade_count),
    totalReturnPct: num(m.total_return_pct), winRate: num(m.win_rate), maxDrawdownPct: num(m.max_drawdown_pct), profitFactor: num(m.profit_factor),
    provenance: {
      schema: str(p.schema), dataTo: str(data.snapshot_as_of), windowLastSession: str(data.window_last_session),
      codeVersion: str(p.code_version), specSha: str(rule.spec_sha256), exitRulesVersion: str(rule.exit_rules_version),
      costModel: str(cost.version), slippagePctPerSide: num(cost.slippage_pct_per_side), brokerageRsPerSide: num(cost.brokerage_rs_per_side),
      universeBasis: str(uni.basis) ?? str(m.universe_basis), universeWarning: str(uni.warning) ?? str(m.universe_warning),
      universeRuleVersion: str(uniRule.version) ?? str(rec(m.universe_rule).version), universeRef: str(uni.ref),
      entryTiming: str(p.entry_timing),
      notRecorded: Array.isArray(p.not_recorded) ? p.not_recorded.flatMap((x) => (str(x) ? [str(x) as string] : [])) : [],
    },
    sweep: rows.length ? { basis: str(sw.basis), rows } : null,
  };
}

/** True when the run's universe carried survivorship bias (an index applied with its latest constituents). */
export const survivorshipBiased = (basis: string | null) => basis === "latest_snapshot" || basis === "present_day_fallback";

export function useBacktestRun() {
  return useMutation({
    mutationFn: async (v: { id: string; from: string; to: string }): Promise<BacktestRun> => readBacktest((await http({
      method: "POST", path: `/api/strategy-builder/strategies/${encodeURIComponent(v.id)}/backtest`,
      body: { from_date: v.from, to_date: v.to }, noRetry: true, timeoutMs: 90_000,
    })).data),
  });
}
