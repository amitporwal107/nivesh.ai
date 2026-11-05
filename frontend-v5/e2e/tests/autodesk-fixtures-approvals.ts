/**
 * Approval queue fixtures for autodesk-approvals.spec.ts.
 *
 * // MOCK — not real data. Bodies copy the shapes of the real desk API (GET /approvals, /approvals/{id},
 * // /trade-plans/{id}?version=, /trade-plans/{id}/versions, /risk/assessments/{id}, /risk/portfolio/{account_id},
 * // /signals/{id}; backend/autodesk/routers/api.py + contracts.py). Figures follow the Phase 1 real-data run of
 * // 5 Nov 2026 (test_reports/autodesk_phase1_20261105_1255.md): PETRONET 310/335 CE × 4 lots at a 6.35 debit, max loss
 * // ₹48,425.90 inside 0.5% of ₹1 Cr; GRASIM ₹41,683.00; ADANIPORTS ₹36,244.39; verdict PASS; decided by
 * // MIDDLE_OFFICE@autodesk-mo-v1. Here PETRONET and GRASIM wait on a person on an ASSISTED account (Desk B).
 */
import { ACCOUNT_A, NOW, TENANT, reply, type Handler, type Req, type RouteValue } from "./autodesk-mock";

export const ACCOUNT_B = { ...ACCOUNT_A, account_id: "ACC-7c1e04b9a25d4f6e8b30", name: "Desk B", operating_mode: "ASSISTED", policy_id: "POL-1b7e93c4d05a4e2f9c61" };

/** 64-hex plan hashes (sha256 shape) of the plan versions the requests bind. */
export const HASH_P = "9f3c41d7a2b84e6c0d5f17a39b2c8e4f6a1d0b3c5e7f9a2b4c6d8e0f1a3ba21e";
export const HASH_G = "41d0e7a9c3b25f84d6e1a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b17b2c";

const POLICY = { policy_id: "POL-1b7e93c4d05a4e2f9c61", policy_version: 1 };

function optLeg(id: string, under: string, strike: string, side: "LONG" | "SHORT", lots: number, lot: number, px: string, expiry: string, oi: number) {
  return { leg_id: id, kind: "CE", underlying: under, tradingsymbol: null, expiry, strike, side, lots, lot_size: lot, quantity: lots * lot, ref_price: px, ref_price_source: "fno_bhavcopy.close 2026-11-04", open_interest: oi, greeks: null };
}

function body(o: { instrument: string; account_id: string; signal_id: string; legs: unknown[]; max_loss: string; max_profit: string; breakeven: string; capital: string; rr: string; sector: string; thesis: string; rationale: string[]; invalidation: string }) {
  return {
    thesis: o.thesis, rationale: o.rationale, signal_id: o.signal_id,
    market_context: { direction: "BULLISH", category: "LONG_BUILDUP", signal_score: "72.50", sector: o.sector, vix: "15.19", data_as_of: "2026-11-04T14:00:00+00:00", fno_session: "2026-11-04" },
    account_id: o.account_id, instrument: o.instrument, segment: "OPTIONS", strategy_type: "BULL_CALL_SPREAD", legs: o.legs,
    entry: { order_type: "LIMIT", reference_price: null, zone_low: null, zone_high: null, valid_until: "2026-11-05T10:00:00+00:00", max_slippage_pct: "0.5" },
    invalidation: { underlying_level: o.invalidation, rule: "close the position when the underlying closes beyond the invalidation level", max_loss_rs: o.max_loss },
    targets: [], max_loss_rs: o.max_loss, max_profit_rs: o.max_profit, loss_defined: true, breakevens: [o.breakeven],
    expected_payoff: { reward_risk: o.rr, reward_rs: o.max_profit, assumptions: ["prices are the previous session's closes (bhavcopy for F&O)", "costs from the desk cost card desk-cost-v2", "a calculation at the prices shown, not a forecast"] },
    capital_required_rs: o.capital, margin_estimate: { amount_rs: o.capital, method: "premium paid", source: "plan legs", fno: true }, net_greeks: null,
    volatility: { iv_source: "Black-76 implied from bhavcopy closes (model)", vix: "15.19" }, liquidity: { min_leg_open_interest: 412300, note: "the risk engine checks 20-session average traded value" },
    holding: { timeframe: "POSITIONAL", max_holding_days: 10, expiry: "2026-11-24", close_days_before_expiry: 2 },
    exit_rules: { trailing: "trail-atr-v1 (2 × ATR14), tighten only", time: "after 10 sessions", emergency: "close every leg together if any leg cannot be managed" },
    risk_warnings: [], plan_expires_at: "2026-11-05T10:00:00+00:00",
    provenance: { agent: "TRADING_ASSISTANT", agent_version: "autodesk-ta-v1", rule_version: "ta-rules-v1", data_as_of: "2026-11-04T14:00:00+00:00", chain_as_of: "2026-11-04", inputs: [`signal://${o.signal_id}`], tried: ["BULL_CALL_SPREAD"] },
    costs_estimate: {}, alternatives_considered: [],
  };
}

export const PLAN_P_BODY = body({
  instrument: "PETRONET", account_id: ACCOUNT_B.account_id, signal_id: "SIG-a41f0c9e7b2d3e5f6a7b",
  legs: [optLeg("L1", "PETRONET", "310", "LONG", 4, 1900, "9.80", "2026-11-24", 412300), optLeg("L2", "PETRONET", "335", "SHORT", 4, 1900, "3.45", "2026-11-24", 538100)],
  max_loss: "48425.90", max_profit: "141574.10", breakeven: "316.37", capital: "48260.00", rr: "2.92", sector: "Oil Gas & Consumable Fuels",
  thesis: "PETRONET: bullish view from a long buildup signal; expressed as a bull call spread 310/335 CE with an invalidation level at 298.40.",
  rationale: ["futures open interest up with price on 2026-11-04", "the spread caps the loss at the premium paid"], invalidation: "298.40",
});

export const PLAN_G_BODY = body({
  instrument: "GRASIM", account_id: ACCOUNT_B.account_id, signal_id: "SIG-b52e1d0f8c3e4f607182",
  legs: [optLeg("L1", "GRASIM", "2700", "LONG", 1, 250, "233.10", "2026-11-24", 61250), optLeg("L2", "GRASIM", "2800", "SHORT", 1, 250, "66.70", "2026-11-24", 80500)],
  max_loss: "41683.00", max_profit: "58317.00", breakeven: "2866.73", capital: "41600.00", rr: "1.40", sector: "Construction Materials",
  thesis: "GRASIM: bullish view from a long buildup signal; expressed as a bull call spread 2700/2800 CE with an invalidation level at 2612.00.",
  rationale: ["futures open interest up with price on 2026-11-04"], invalidation: "2612.00",
});

const chk = (name: string, outcome: string, detail: string, value: string | null = null, limit: string | null = null, hard = true) => ({ name, outcome, value, limit, detail, hard });

export const RISK_P = {
  assessment_id: "RSK-5e0a7c3b91d24f68a0b1", trade_id: "TRD-8d2c6f1a0b3e4d5c6e7f", plan_version: 1, account_id: ACCOUNT_B.account_id, simulation_id: null, verdict: "PASS",
  body: {
    verdict: "PASS",
    checks: [
      chk("inputs_fresh", "PASS", "data 1 session old (limit 1)"), chk("account_active", "PASS", "account is ACTIVE"),
      chk("strategy_allowed", "PASS", "BULL_CALL_SPREAD is allowed"), chk("segment_allowed", "PASS", "all leg segments allowed"),
      chk("legs_valid", "PASS", "2 legs, lot size 1900 matches the exchange"), chk("defined_risk", "PASS", "defined risk"),
      chk("expiry", "PASS", "expiry 2026-11-24 is 13 sessions away"), chk("liquidity", "PASS", "liquid", "128400000.00", "50000000.00"),
      chk("credit_terms", "SKIPPED", "not a credit structure"), chk("reward_risk", "PASS", "reward 141574.10 : loss 48425.90 = 2.92 vs 1.5", "2.92", "1.5"),
      chk("per_trade_risk", "PASS", "loss 48425.90 (0.484% of equity) vs limit 0.5%", "48425.90", "50000.00"),
      chk("position", "PASS", "capital used 48260.00 (premium paid) vs 10% of equity", "48260.00", "1000000.00"),
      chk("open_risk", "PASS", "open risk incl. 1 approved plans 84670.29 (0.847%) vs 3%", "84670.29", "300000.00"),
      chk("sector", "WARN", "sector Oil Gas & Consumable Fuels: capital incl. approved plans 48260.00 vs 25% of equity", "48260.00", "2500000.00"),
      chk("margin_utilization", "PASS", "F&O capital incl. approved plans 84398.00 (0.844%) vs 60% (estimate, not SPAN)", "84398.00", "6000000.00"),
      chk("daily_loss", "SKIPPED", "no positions until Phase 2 (no fills, so no realised or unrealised P&L yet)"),
      chk("weekly_loss", "SKIPPED", "no positions until Phase 2 (no fills, so no realised or unrealised P&L yet)"),
      chk("drawdown", "SKIPPED", "no positions until Phase 2 (no fills, so no realised or unrealised P&L yet)"),
    ],
    sizing: { proposed_size: 4, allowed_size: 4, unit: "lots per leg", budget_rs: "50000.00", loss_rs: "48425.90", capital_rs: "48260.00", capital_method: "premium paid", method: "fixed risk per trade (policy per_trade_risk_pct of equity)" },
    violations: [], warnings: [],
    inputs_snapshot: { equity_rs: "10000000.00", pending_commitments: 1, pending_risk_rs: "36244.39", pending_fno_capital_rs: "36138.00", sector: "Oil Gas & Consumable Fuels", as_of: "2026-11-05T03:30:00+00:00", session_date: "2026-11-05", book_basis: "Phase 1: equity = starting capital; commitments = approved, unexpired plans (no fills yet)" },
  },
  ...POLICY, engine_version: "autodesk-risk-v1", created_at: "2026-11-05T03:31:10.880+00:00",
};

export const RISK_G = {
  ...RISK_P, assessment_id: "RSK-6f1b8d4ca2e35079b1c2", trade_id: "TRD-9e3d7a2b1c4f5e6d7f80",
  body: { ...RISK_P.body, checks: RISK_P.body.checks.map((c) => (c.name === "per_trade_risk" ? chk("per_trade_risk", "PASS", "loss 41683.00 (0.417% of equity) vs limit 0.5%", "41683.00", "50000.00") : c)), sizing: { ...RISK_P.body.sizing, proposed_size: 1, allowed_size: 1, loss_rs: "41683.00", capital_rs: "41600.00" } },
  created_at: "2026-11-05T03:31:42.120+00:00",
};

export const RISK_A = { ...RISK_P, assessment_id: "RSK-7a2c9e5db3f4618ac2d3", trade_id: "TRD-7c1b5e09fa2d3c4b5a6e", account_id: ACCOUNT_A.account_id, created_at: "2026-11-05T03:31:29.400+00:00" };

const apr = (o: Record<string, unknown>) => ({
  plan_version: 1, account_id: ACCOUNT_B.account_id, simulation_id: null, supersedes_id: null, expires_at: "2026-11-05T10:00:00+00:00", ...o,
});

export const APR_P = apr({
  approval_id: "APR-3f2a9c41d07b5e8a12c4", trade_id: RISK_P.trade_id, status: "NEEDS_HUMAN_APPROVAL", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1",
  body: { trade_id: RISK_P.trade_id, plan_version: 1, account_id: ACCOUNT_B.account_id, simulation_id: null, status: "NEEDS_HUMAN_APPROVAL", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1", reasons: ["assisted mode: a person approves every plan"], scope: null, risk_assessment_id: RISK_P.assessment_id, ...POLICY, expires_at: "2026-11-05T10:00:00+00:00", created_at: "2026-11-05T03:31:11.540+00:00" },
  risk_assessment_id: RISK_P.assessment_id, created_at: "2026-11-05T03:31:11.540+00:00",
});

export const APR_G = apr({
  approval_id: "APR-4a3b0d52e18c6f9b23d5", trade_id: RISK_G.trade_id, status: "NEEDS_HUMAN_APPROVAL", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1",
  body: { ...(APR_P.body as object), trade_id: RISK_G.trade_id, reasons: ["assisted mode: a person approves every plan"], risk_assessment_id: RISK_G.assessment_id, created_at: "2026-11-05T03:31:42.560+00:00" },
  risk_assessment_id: RISK_G.assessment_id, created_at: "2026-11-05T03:31:42.560+00:00",
});

/** A simulation's request: never in the desk queue. */
export const APR_SIM = apr({ approval_id: "APR-9c8b7a6f5e4d3c2b1a09", trade_id: "TRD-sim0001", simulation_id: "SIM-2b9d7f1e0a3c4b5d6e7f", account_id: "ACC-sim", status: "NEEDS_HUMAN_APPROVAL", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1", body: { reasons: ["assisted mode: a person approves every plan"] }, risk_assessment_id: null, created_at: "2026-11-05T03:40:00+00:00" });

/** Approved by the Middle Office on Desk A (autonomous paper, within policy) — today 09:01 IST. */
export const APR_ADANI = apr({
  approval_id: "APR-1d9e8f7a6b5c4d3e2f10", trade_id: "TRD-7c1b5e09fa2d3c4b5a6e", account_id: ACCOUNT_A.account_id, status: "APPROVED", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1",
  body: { status: "APPROVED", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1", reasons: ["within the autonomy rules of the policy", "risk 0.36% of equity"], scope: { tenant_id: TENANT, account_id: ACCOUNT_A.account_id, trade_id: "TRD-7c1b5e09fa2d3c4b5a6e", plan_version: 1, instrument: "ADANIPORTS", strategy_type: "BULL_CALL_SPREAD", max_lots: 2, max_notional_rs: "63232.00", max_risk_rs: "36244.39", execution_mode: "PAPER", allowed_actions: ["ENTER", "EXIT_AT_INVALIDATION", "EXIT_AT_TARGET", "TRAIL_TIGHTEN", "TIME_EXIT"], plan_hash: HASH_G } },
  risk_assessment_id: "RSK-7a2c9e5db3f4618ac2d3", created_at: "2026-11-05T03:31:30.010+00:00",
});

/** Rejected by the Middle Office (risk FAIL) — today 09:02 IST. */
export const APR_REJ = apr({
  approval_id: "APR-2e0f9a8b7c6d5e4f3a21", trade_id: "TRD-6b0a4d98e91c2b3a4f5d", account_id: ACCOUNT_A.account_id, status: "REJECTED", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1",
  body: { status: "REJECTED", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1", reasons: ["risk checks failed: per_trade_risk"], scope: null },
  risk_assessment_id: null, created_at: "2026-11-05T03:32:05.300+00:00",
});

export const PLAN_A_BODY = body({
  instrument: "ADANIPORTS", account_id: ACCOUNT_A.account_id, signal_id: "SIG-c63f2e1a9d4f5a708293",
  legs: [optLeg("L1", "ADANIPORTS", "1400", "LONG", 2, 475, "52.30", "2026-11-24", 95475), optLeg("L2", "ADANIPORTS", "1500", "SHORT", 2, 475, "14.26", "2026-11-24", 120650)],
  max_loss: "36244.39", max_profit: "58755.61", breakeven: "1438.15", capital: "36138.00", rr: "1.62", sector: "Services",
  thesis: "ADANIPORTS: bullish view from a long buildup signal; expressed as a bull call spread 1400/1500 CE with an invalidation level at 1362.00.",
  rationale: ["futures open interest up with price on 2026-11-04"], invalidation: "1362.00",
});

export const SIGNAL_P = { signal_id: "SIG-a41f0c9e7b2d3e5f6a7b", instrument: "PETRONET", direction: "BULLISH", category: "LONG_BUILDUP", signal_score: "72.50", created_at: "2026-11-05T03:15:42.000+00:00" };
export const SIGNAL_G = { ...SIGNAL_P, signal_id: "SIG-b52e1d0f8c3e4f607182", instrument: "GRASIM", created_at: "2026-11-05T03:15:44.000+00:00" };

export const HEADS = [
  { trade_id: APR_ADANI.trade_id, account_id: ACCOUNT_A.account_id, simulation_id: null, workflow_id: "WF-1", signal_id: "SIG-x", instrument: "ADANIPORTS", strategy_type: "BULL_CALL_SPREAD", current_version: 1, status: "APPROVED", created_at: "2026-11-05T03:30:00+00:00", updated_at: "2026-11-05T03:31:30+00:00" },
  { trade_id: APR_REJ.trade_id, account_id: ACCOUNT_A.account_id, simulation_id: null, workflow_id: "WF-2", signal_id: "SIG-y", instrument: "TATAPOWER", strategy_type: "LONG_FUTURES", current_version: 1, status: "REJECTED", created_at: "2026-11-05T03:31:50+00:00", updated_at: "2026-11-05T03:32:05+00:00" },
];

export interface ApprovalsWorld {
  plans: Record<string, { head: Record<string, unknown>; versions: Record<number, { body: unknown; hash: string; created_at: string; created_by: string; change_reason: string | null }>; risk: Record<number, unknown> }>;
  approvals: Record<string, Record<string, unknown>>;
  answers: Record<string, unknown>[];
  signals: Record<string, unknown>;
  risks: Record<string, unknown>;
}

export function world(): ApprovalsWorld {
  const head = (trade_id: string, instrument: string, wf: string, sig: string) => ({ trade_id, account_id: ACCOUNT_B.account_id, simulation_id: null, workflow_id: wf, signal_id: sig, instrument, strategy_type: "BULL_CALL_SPREAD", current_version: 1, status: "AWAITING_APPROVAL", created_at: "2026-11-05T03:31:05+00:00", updated_at: "2026-11-05T03:31:11+00:00" });
  return {
    plans: {
      [RISK_P.trade_id]: { head: head(RISK_P.trade_id, "PETRONET", "WF-0c1d2e3f4a5b6c7d8e9f", SIGNAL_P.signal_id), versions: { 1: { body: PLAN_P_BODY, hash: HASH_P, created_at: "2026-11-05T03:31:05.410+00:00", created_by: "TRADING_ASSISTANT", change_reason: null } }, risk: { 1: RISK_P } },
      [APR_ADANI.trade_id as string]: { head: { ...head(APR_ADANI.trade_id as string, "ADANIPORTS", "WF-2e3f4a5b6c7d8e9f0a1b", "SIG-c63f2e1a9d4f5a708293"), account_id: ACCOUNT_A.account_id, status: "APPROVED" }, versions: { 1: { body: PLAN_A_BODY, hash: HASH_G, created_at: "2026-11-05T03:31:25.000+00:00", created_by: "TRADING_ASSISTANT", change_reason: null } }, risk: { 1: RISK_A } },
      [RISK_G.trade_id]: { head: head(RISK_G.trade_id, "GRASIM", "WF-1d2e3f4a5b6c7d8e9f0a", SIGNAL_G.signal_id), versions: { 1: { body: PLAN_G_BODY, hash: HASH_G, created_at: "2026-11-05T03:31:38.900+00:00", created_by: "TRADING_ASSISTANT", change_reason: null } }, risk: { 1: RISK_G } },
    },
    approvals: Object.fromEntries([APR_P, APR_G, APR_SIM, APR_ADANI, APR_REJ].map((a) => [a.approval_id as string, a as Record<string, unknown>])),
    answers: [],
    signals: { [SIGNAL_P.signal_id]: SIGNAL_P, [SIGNAL_G.signal_id]: SIGNAL_G, "SIG-c63f2e1a9d4f5a708293": { ...SIGNAL_P, signal_id: "SIG-c63f2e1a9d4f5a708293", instrument: "ADANIPORTS", created_at: "2026-11-05T03:15:40.000+00:00" } },
    risks: { [RISK_P.assessment_id]: RISK_P, [RISK_G.assessment_id]: RISK_G, [RISK_A.assessment_id]: RISK_A },
  };
}

const nf = (id: string) => reply(404, { error: "NOT_FOUND", message: `not found: ${id}` });
const STATUS_OF: Record<string, string> = { APPROVE: "APPROVED", REJECT: "REJECTED", REQUEST_REVISION: "NEEDS_REVISION" };

/** Routes of the approval screen over a mutable world (a decision changes what the next GETs return, as the API does). */
export function approvalsRoutes(w: ApprovalsWorld, over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  const answered = (id: string) => w.answers.some((x) => (x as { supersedes_id: string }).supersedes_id === id);
  const all = () => [...Object.values(w.approvals), ...w.answers] as Record<string, unknown>[];
  const routes: Record<string, RouteValue> = {
    "GET /approvals": ((r: Req) => {
      const rows = all().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
      if (r.query.get("pending") === "true") return rows.filter((a) => a.status === "NEEDS_HUMAN_APPROVAL" && !answered(String(a.approval_id)));
      return rows;
    }) as Handler,
    "GET /approvals/:id": ((r: Req) => all().find((a) => a.approval_id === r.params.id) ?? nf(r.params.id)) as Handler,
    "GET /trade-plans": HEADS,
    "GET /trade-plans/:id": ((r: Req) => {
      const p = w.plans[r.params.id];
      if (!p) return nf(r.params.id);
      const v = Number(r.query.get("version") ?? p.head.current_version);
      const ver = p.versions[v];
      if (!ver) return nf(`${r.params.id}@${v}`);
      return { ...p.head, version: v, body: ver.body, body_sha256: "b".repeat(64), version_created_by: ver.created_by, change_reason: ver.change_reason, plan_hash: ver.hash, latest_risk_assessment: p.risk[v] ?? null, approvals: all().filter((a) => a.trade_id === r.params.id).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))) };
    }) as Handler,
    "GET /trade-plans/:id/versions": ((r: Req) => {
      const p = w.plans[r.params.id];
      if (!p) return nf(r.params.id);
      return Object.entries(p.versions).map(([v, x]) => {
        const b = x.body as { max_loss_rs: string; max_profit_rs: string; capital_required_rs: string };
        return { trade_id: r.params.id, version: Number(v), body: x.body, body_sha256: "b".repeat(64), strategy_type: "BULL_CALL_SPREAD", max_loss_rs: b.max_loss_rs, max_profit_rs: b.max_profit_rs, capital_required_rs: b.capital_required_rs, created_by: x.created_by, change_reason: x.change_reason, supersedes_version: Number(v) > 1 ? Number(v) - 1 : null, created_at: x.created_at };
      });
    }) as Handler,
    "GET /risk/assessments/:id": ((r: Req) => w.risks[r.params.id] ?? nf(r.params.id)) as Handler,
    "GET /risk/portfolio/:id": ((r: Req) => ({
      account: r.params.id === ACCOUNT_B.account_id ? ACCOUNT_B : ACCOUNT_A,
      book: { account_id: r.params.id, equity_rs: "10000000.00", starting_capital_rs: "10000000.00", pending: [{ trade_id: "TRD-7c1b5e09fa2d3c4b5a6e", plan_version: 1, instrument: "ADANIPORTS", sector: "Services", strategy_type: "BULL_CALL_SPREAD", max_loss_rs: "36244.39", capital_rs: "36138.00", fno: true }], basis: "Phase 1: equity = starting capital; commitments = approved, unexpired plans (no fills yet)" },
      note: "Phase 1: commitments are approved, unexpired plans; there are no fills or positions yet",
    })) as Handler,
    "GET /signals/:id": ((r: Req) => w.signals[r.params.id] ?? nf(r.params.id)) as Handler,
    "POST /approvals/:id/decision": ((r: Req) => {
      const req = w.approvals[r.params.id];
      if (!req) return nf(r.params.id);
      if (answered(r.params.id)) return reply(409, { error: "CONFLICT", message: "this approval request has already been answered" });
      const b = r.body as { decision: string; reason: string; plan_hash?: string };
      const status = STATUS_OF[b.decision];
      const row = {
        approval_id: `APR-ans${w.answers.length}${"0".repeat(14)}`, trade_id: req.trade_id, plan_version: req.plan_version, account_id: req.account_id, simulation_id: req.simulation_id,
        status, decided_by: `user:${TENANT}`, body: { status, decided_by: `user:${TENANT}`, reasons: [b.reason || (status === "APPROVED" ? "approved by a person" : status === "REJECTED" ? "rejected by a person" : "revision requested")] },
        risk_assessment_id: req.risk_assessment_id, supersedes_id: req.approval_id, expires_at: status === "APPROVED" ? req.expires_at : null, created_at: NOW,
      };
      w.answers.push(row);
      return reply(201, row);
    }) as Handler,
  };
  return { ...routes, ...over };
}
